from contextlib import AsyncExitStack
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import subprocess
import json
from pathlib import Path
from datetime import datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google.genai.types import GenerateContentConfig

from velociraptor.llm.gemini import Gemini
from velociraptor.models.attachment import Attachment
from velociraptor.models.conversation import (
    ConversationHistory, 
    ConversationMessage, 
    MessagePart, 
    MessageType,
    ToolCall,
    ToolResult
)
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MCPServer:
    """Configuration for an MCP server connection."""
    name: str
    container_pattern: str  # Pattern to match container names
    module_path: str
    description: str
    container_name: Optional[str] = None  # Actual resolved container name


class MCPGeminiClient:
    """MCP-enhanced Gemini client using native SDK MCP support."""

    def __init__(self):
        self.gemini = Gemini()
        self.exit_stack: Optional[AsyncExitStack] = None
        self.mcp_sessions: List[ClientSession] = []
        self.context_file_path = Path(".context.json")
        
        # Configure MCP servers from docker-compose.yml
        self.servers = [
            MCPServer(
                name="semantic_search",
                container_pattern="semantic-search",
                module_path="velociraptor.mcp.semantic_search_mcp",
                description="Semantic search using vector embeddings"
            ),
            MCPServer(
                name="page_fetch",
                container_pattern="page-fetch", 
                module_path="velociraptor.mcp.page_fetch_mcp",
                description="Fetch page images as base64"
            ),
            MCPServer(
                name="neo4j_fulltext",
                container_pattern="neo4j-fulltext-search",
                module_path="velociraptor.mcp.neo4j_full_text_search_mcp", 
                description="Neo4j full-text search with security restrictions"
            ),
            MCPServer(
                name="neo4j_cypher",
                container_pattern="neo4j-cypher",
                module_path="mcp_neo4j_cypher.server",
                description="General Neo4j Cypher query execution - provides read_neo4j_cypher, write_neo4j_cypher, and get_neo4j_schema tools for full database access, schema exploration, and complex graph traversals"
            )
        ]

    async def __aenter__(self):
        """Async context manager entry - connect to all MCP servers."""
        self.exit_stack = AsyncExitStack()
        await self.exit_stack.__aenter__()
        await self.connect_to_servers()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - cleanup connections."""
        if self.exit_stack:
            await self.exit_stack.aclose()

    def _discover_container_names(self) -> None:
        """Discover actual container names from running Docker containers."""
        try:
            # Get list of running containers
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True,
                text=True,
                check=True
            )
            
            running_containers = result.stdout.strip().split('\n') if result.stdout.strip() else []
            logger.info(f"Found {len(running_containers)} running containers")
            
            # Match containers to server patterns
            for server in self.servers:
                matching_containers = [
                    name for name in running_containers 
                    if server.container_pattern in name
                ]
                
                if matching_containers:
                    # Use the first match (should typically be only one)
                    server.container_name = matching_containers[0]
                    logger.info(f"Discovered container '{server.container_name}' for server '{server.name}'")
                else:
                    logger.warning(f"No running container found matching pattern '{server.container_pattern}' for server '{server.name}'")
                    
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to discover container names: {e}", exc_info=True)
        except FileNotFoundError:
            logger.error("Docker command not found. Make sure Docker is installed and in PATH", exc_info=True)

    async def connect_to_servers(self) -> None:
        """Connect to all configured MCP servers."""
        logger.info("Connecting to MCP servers...")
        
        # First, discover actual container names
        self._discover_container_names()
        
        for server in self.servers:
            if not server.container_name:
                logger.warning(f"Skipping server '{server.name}' - no container found")
                continue
                
            try:
                session = await self._connect_to_server(server)
                if session:
                    self.mcp_sessions.append(session)
                    logger.info(f"Connected to MCP server: {server.name}")
            except Exception as e:
                logger.error(f"Failed to connect to MCP server {server.name}: {e}", exc_info=True)
                # Continue with other servers even if one fails
        
        logger.info(f"Connected to {len(self.mcp_sessions)} MCP servers")

    async def _connect_to_server(self, server: MCPServer) -> Optional[ClientSession]:
        """Connect to a single MCP server."""
        if not self.exit_stack:
            raise RuntimeError("MCPGeminiClient must be used as async context manager")
            
        try:
            # Handle different command formats for different servers
            if server.name == "neo4j_cypher":
                server_params = StdioServerParameters(
                    command="docker",
                    args=[
                        "exec", "-i", server.container_name,
                        "mcp-neo4j-cypher", "--transport", "stdio"
                    ],
                    env=None
                )
            else:
                server_params = StdioServerParameters(
                    command="docker",
                    args=[
                        "exec", "-i", server.container_name,
                        "python", "-m", server.module_path
                    ],
                    env=None
                )
            
            # Use exit_stack to manage connection lifecycle
            read_stream, write_stream = await self.exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            
            session = await self.exit_stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            
            # Initialize the session
            await session.initialize()
            return session
            
        except Exception as e:
            logger.error(f"Failed to connect to {server.name}: {e}", exc_info=True)
            return None

    async def prompt(
        self, 
        prompt: str, 
        attachments: Optional[List[Attachment]] = None,
        response_json_schema: Optional[Dict] = None
    ) -> str:
        """
        Enhanced prompt method using native Gemini MCP support.
        
        Args:
            prompt: The text prompt to send
            attachments: List of Attachment objects to include
            response_json_schema: JSON schema for response
            
        Returns:
            The string response from the model with MCP tools available
        """
        try:
            logger.info("Processing prompt with MCP tools")
            
            # Prepare content parts
            from google.genai.types import Part
            contents = [Part.from_text(text=prompt)]
            
            # Add attachments if provided
            if attachments:
                import aiofiles
                for attachment in attachments:
                    try:
                        async with aiofiles.open(attachment.file_path, 'rb') as f:
                            file_data = await f.read()

                        file_part = Part.from_bytes(
                            data=file_data,
                            mime_type=attachment.mime_type
                        )
                        contents.append(file_part)
                    except Exception as e:
                        logger.error(f"Failed to read attachment {attachment.file_path}: {e}", exc_info=True)
                        raise

            # Build config with MCP sessions as tools
            config_params = {}
            
            # Add JSON schema if provided
            if response_json_schema:
                config_params.update({
                    "response_mime_type": "application/json",
                    "response_json_schema": response_json_schema
                })
            
            # Add MCP sessions as tools (native SDK support)
            if self.mcp_sessions:
                config_params["tools"] = self.mcp_sessions
                logger.info(f"Using {len(self.mcp_sessions)} MCP tools")
            
            config = GenerateContentConfig(**config_params) if config_params else None

            # Call Gemini with MCP tools
            response = await self.gemini.client.aio.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=config
            )

            # Extract tool usage information from response if available
            tool_calls = []
            tool_results = []
            
            # Debug: Log the full response structure
            logger.debug(f"Response type: {type(response)}")
            logger.debug(f"Response attributes: {dir(response)}")
            
            if hasattr(response, 'candidates') and response.candidates:
                candidate = response.candidates[0]
                logger.debug(f"Candidate type: {type(candidate)}")
                logger.debug(f"Candidate attributes: {dir(candidate)}")
                
                if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                    logger.debug(f"Found {len(candidate.content.parts)} parts in response")
                    for i, part in enumerate(candidate.content.parts):
                        logger.debug(f"Part {i} type: {type(part)}")
                        logger.debug(f"Part {i} attributes: {dir(part)}")
                        
                        # Check if this part contains tool call information
                        if hasattr(part, 'function_call'):
                            logger.info(f"Found function_call in part {i}")
                            tool_calls.append({
                                'name': part.function_call.name if hasattr(part.function_call, 'name') else 'unknown',
                                'parameters': dict(part.function_call.args) if hasattr(part.function_call, 'args') else {}
                            })
                        elif hasattr(part, 'function_response'):
                            logger.info(f"Found function_response in part {i}")
                            tool_results.append({
                                'content': part.function_response,
                                'error': None
                            })
                        elif hasattr(part, 'text') and part.text:
                            # Sometimes tool calls might be embedded in text
                            logger.debug(f"Part {i} contains text: {part.text[:100]}...")
            
            # Also check for usage metadata that might contain tool information
            if hasattr(response, 'usage_metadata'):
                logger.debug(f"Usage metadata: {response.usage_metadata}")
            
            # Try alternative extraction methods for different SDK versions
            if not tool_calls and not tool_results:
                logger.debug("No tool calls found in standard locations, trying alternative extraction")
                try:
                    # Check if response has raw_response or other attributes
                    if hasattr(response, '_raw_response'):
                        logger.debug(f"Raw response type: {type(response._raw_response)}")
                    
                    # Check for tool calls in different response structure
                    if hasattr(response, 'function_calls'):
                        logger.info("Found function_calls in response root")
                        for call in response.function_calls:
                            tool_calls.append({
                                'name': call.name if hasattr(call, 'name') else 'unknown',
                                'parameters': dict(call.args) if hasattr(call, 'args') else {}
                            })
                except Exception as e:
                    logger.debug(f"Alternative extraction failed: {e}")

            # Track tool calls and results in context if any were found
            if tool_calls or tool_results:
                try:
                    self._add_tool_calls_to_context(tool_calls, tool_results)
                    logger.info(f"Tracked {len(tool_calls)} tool calls and {len(tool_results)} results")
                except Exception as e:
                    logger.error(f"Failed to track tool calls in context: {e}", exc_info=True)
            else:
                # If no tool calls were extracted but we have MCP sessions, 
                # tools might have been used transparently by the SDK
                if self.mcp_sessions:
                    logger.info("No tool calls extracted from response, but MCP tools were available")
                    # Add a generic tool usage indicator to context
                    self._add_generic_tool_usage_to_context(prompt, response.text)

            logger.info("Prompt processed successfully with MCP tools")
            return response.text
            
        except Exception as e:
            logger.error(f"Error in MCP-enhanced prompt: {e}", exc_info=True)
            # Fallback to regular Gemini prompt without MCP
            logger.info("Falling back to regular Gemini prompt")
            return await self.gemini.prompt(prompt, attachments, response_json_schema)

    async def get_available_tools(self) -> Dict[str, List[str]]:
        """Get list of available tools from all connected MCP servers."""
        tools_by_server = {}
        
        for i, session in enumerate(self.mcp_sessions):
            try:
                server_name = self.servers[i].name if i < len(self.servers) else f"server_{i}"
                tools_response = await session.list_tools()
                tool_names = [tool.name for tool in tools_response.tools]
                tools_by_server[server_name] = tool_names
            except Exception as e:
                logger.error(f"Failed to list tools from session {i}: {e}", exc_info=True)
                
        return tools_by_server

    async def get_connection_status(self) -> Dict[str, bool]:
        """Get connection status for all configured servers."""
        status = {}
        for i, server in enumerate(self.servers):
            status[server.name] = i < len(self.mcp_sessions)
        return status

    def _load_conversation_context(self) -> Optional[ConversationHistory]:
        """Load existing conversation context from .context.json."""
        try:
            if self.context_file_path.exists():
                with open(self.context_file_path, 'r', encoding='utf-8') as f:
                    json_content = f.read()
                return ConversationHistory.from_json(json_content)
        except Exception as e:
            logger.error(f"Error loading conversation context: {e}", exc_info=True)
        return None

    def _save_conversation_context(self, context: ConversationHistory) -> None:
        """Save conversation context to .context.json."""
        try:
            with open(self.context_file_path, 'w', encoding='utf-8') as f:
                f.write(context.to_json())
            logger.info(f"Context saved with {len(context.messages)} messages")
        except Exception as e:
            logger.error(f"Error saving conversation context: {e}", exc_info=True)

    def _add_tool_calls_to_context(self, tool_calls: List[Dict[str, Any]], tool_results: List[Dict[str, Any]]) -> None:
        """Add tool calls and results to the conversation context."""
        try:
            context = self._load_conversation_context()
            if not context:
                logger.warning("No conversation context found, creating new context for tool tracking")
                # Create a basic context if none exists
                context = ConversationHistory(messages=[])

            logger.info(f"Adding {len(tool_calls)} tool calls and {len(tool_results)} tool results to context")

            # Create tool call objects
            tracked_tool_calls = []
            for i, call in enumerate(tool_calls):
                tool_call = ToolCall(
                    tool_name=call.get('name', f'unknown_tool_{i}'),
                    tool_id=f"call_{i}_{int(datetime.now().timestamp() * 1000)}",
                    parameters=call.get('parameters', {})
                )
                tracked_tool_calls.append(tool_call)
                logger.debug(f"Created tool call: {tool_call.tool_name} with ID {tool_call.tool_id}")

            # Create tool result objects
            tracked_tool_results = []
            for i, result in enumerate(tool_results):
                # Match results to tool calls when possible
                tool_call_id = tracked_tool_calls[i].tool_id if i < len(tracked_tool_calls) else f"result_{i}_{int(datetime.now().timestamp() * 1000)}"
                
                # Handle different result formats
                result_content = result
                error_content = None
                
                if isinstance(result, dict):
                    result_content = result.get('content', result)
                    error_content = result.get('error')
                
                tool_result = ToolResult(
                    tool_call_id=tool_call_id,
                    result=result_content,
                    error=error_content
                )
                tracked_tool_results.append(tool_result)
                logger.debug(f"Created tool result for call ID {tool_call_id}")

            # Add tool call message
            if tracked_tool_calls:
                logger.info(f"Adding tool call message with {len(tracked_tool_calls)} calls")
                tool_call_message = ConversationMessage(
                    type=MessageType.TOOL_CALL,
                    parts=[MessagePart(type="text", content=f"Executed {len(tracked_tool_calls)} tool calls")],
                    tool_calls=tracked_tool_calls,
                    timestamp=datetime.now().isoformat()
                )
                context.add_message(tool_call_message)

            # Add tool result message
            if tracked_tool_results:
                logger.info(f"Adding tool result message with {len(tracked_tool_results)} results")
                tool_result_message = ConversationMessage(
                    type=MessageType.TOOL_RESULT,
                    parts=[MessagePart(type="text", content=f"Tool results for {len(tracked_tool_results)} calls")],
                    tool_results=tracked_tool_results,
                    timestamp=datetime.now().isoformat()
                )
                context.add_message(tool_result_message)

            # Save the updated context
            self._save_conversation_context(context)
            logger.info("Successfully added tool calls and results to context")
            
        except Exception as e:
            logger.error(f"Failed to add tool calls to context: {e}", exc_info=True)
            raise

    def _add_generic_tool_usage_to_context(self, prompt: str, response: str) -> None:
        """Add a generic tool usage indicator when tools might have been used transparently."""
        try:
            context = self._load_conversation_context()
            if not context:
                logger.debug("No conversation context found, skipping generic tool usage tracking")
                return

            # Check if the response seems to contain tool-derived information
            # This is a heuristic approach since we can't detect tool usage directly
            tool_indicators = [
                "based on the search",
                "according to the data",
                "from the database",
                "search results show",
                "the query returned",
                "found in the system"
            ]
            
            likely_used_tools = any(indicator in response.lower() for indicator in tool_indicators)
            
            if likely_used_tools:
                logger.info("Response appears to contain tool-derived information, adding to context")
                
                # Create a generic tool usage message
                tool_usage_message = ConversationMessage(
                    type=MessageType.TOOL_CALL,
                    parts=[MessagePart(type="text", content="MCP tools may have been used transparently by the SDK")],
                    tool_calls=[ToolCall(
                        tool_name="mcp_transparent_tools",
                        tool_id=f"transparent_{int(datetime.now().timestamp() * 1000)}",
                        parameters={"prompt_hint": prompt[:100] + "..." if len(prompt) > 100 else prompt}
                    )],
                    timestamp=datetime.now().isoformat()
                )
                context.add_message(tool_usage_message)
                self._save_conversation_context(context)
                logger.debug("Added generic tool usage indicator to context")
            else:
                logger.debug("Response doesn't appear to contain tool-derived information")
                
        except Exception as e:
            logger.error(f"Failed to add generic tool usage to context: {e}", exc_info=True)


# Enhanced Gemini class that includes MCP support
class GeminiWithMCP(Gemini):
    """Extended Gemini class with built-in MCP support."""
    
    def __init__(self):
        super().__init__()
        self.mcp_client: Optional[MCPGeminiClient] = None
    
    async def enable_mcp(self) -> None:
        """Enable MCP support by connecting to MCP servers."""
        if not self.mcp_client:
            self.mcp_client = MCPGeminiClient()
            await self.mcp_client.__aenter__()
            logger.info("MCP support enabled")
    
    async def disable_mcp(self) -> None:
        """Disable MCP support and cleanup connections."""
        if self.mcp_client:
            await self.mcp_client.__aexit__(None, None, None)
            self.mcp_client = None
            logger.info("MCP support disabled")
    
    async def prompt(
        self, 
        prompt: str, 
        attachments: Optional[List[Attachment]] = None, 
        response_json_schema: Optional[Dict] = None, 
        retry_count: int = 0,
        use_mcp: bool = True
    ) -> str:
        """
        Enhanced prompt method with optional MCP support.
        
        Args:
            prompt: The text prompt to send
            attachments: List of Attachment objects to include
            response_json_schema: JSON schema for response
            retry_count: Current retry attempt (internal use)
            use_mcp: Whether to use MCP tools (default: True)
            
        Returns:
            The string response from the model
        """
        # Use MCP if enabled and requested
        if use_mcp and self.mcp_client:
            try:
                return await self.mcp_client.prompt(prompt, attachments, response_json_schema)
            except Exception as e:
                logger.warning(f"MCP prompt failed, falling back to regular prompt: {e}")
        
        # Fallback to regular prompt
        return await super().prompt(prompt, attachments, response_json_schema, retry_count)


# Convenience functions
async def prompt_with_mcp(
    prompt: str, 
    attachments: Optional[List[Attachment]] = None,
    response_json_schema: Optional[Dict] = None
) -> str:
    """
    Convenience function to prompt with MCP tool support.
    Creates a new client instance, processes the prompt, and cleans up.
    """
    async with MCPGeminiClient() as client:
        return await client.prompt(prompt, attachments, response_json_schema)


async def create_mcp_enabled_gemini() -> GeminiWithMCP:
    """
    Create a Gemini instance with MCP support enabled.
    Remember to call disable_mcp() when done to cleanup connections.
    """
    gemini = GeminiWithMCP()
    await gemini.enable_mcp()
    return gemini