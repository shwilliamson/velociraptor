from contextlib import AsyncExitStack
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import subprocess
import json
from pathlib import Path
from datetime import datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google.genai.types import GenerateContentConfig, FunctionDeclaration, Tool

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

# Forward reference for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from velociraptor.utils.context_manager import ContextManager

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
    """MCP-enhanced Gemini client using manual function calling for full conversational control."""

    def __init__(self, context_manager: Optional['ContextManager'] = None):
        self.gemini = Gemini()
        self.exit_stack: Optional[AsyncExitStack] = None
        self.mcp_sessions: List[ClientSession] = []
        self.context_manager = context_manager
        
        # Tool registry mapping tool names to MCP sessions and metadata
        self.tool_registry: Dict[str, Dict[str, Any]] = {}
        
        # Function schemas for Gemini function calling
        self.function_declarations: List[FunctionDeclaration] = []
        
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
            ),
            MCPServer(
                name="sequential_thinking",
                container_pattern="sequential-thinking",
                module_path="mcp_sequential_thinking.server",
                description="Sequential thinking server for structured reasoning and step-by-step problem solving"
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
        
        # Register all available tools for function calling
        await self._register_tools()

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
            elif server.name == "sequential_thinking":
                server_params = StdioServerParameters(
                    command="docker",
                    args=[
                        "exec", "-i", server.container_name,
                        "node", "dist/index.js"
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

    async def _register_tools(self) -> None:
        """Register all available MCP tools for function calling."""
        logger.info("Registering MCP tools for function calling...")
        
        self.tool_registry.clear()
        self.function_declarations.clear()
        
        for i, session in enumerate(self.mcp_sessions):
            try:
                server_name = self.servers[i].name if i < len(self.servers) else f"server_{i}"
                
                # Get available tools from this MCP server
                tools_response = await session.list_tools()
                
                for tool in tools_response.tools:
                    # Skip write tools for read-only operation
                    if tool.name == "write_neo4j_cypher":
                        logger.info(f"Skipping write tool: {tool.name}")
                        continue
                    
                    # Register tool in our registry
                    self.tool_registry[tool.name] = {
                        'session': session,
                        'server_name': server_name,
                        'description': tool.description or f"Tool from {server_name}",
                        'input_schema': tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                    }
                    
                    # Create function declaration for Gemini with sanitized schema
                    input_schema = tool.inputSchema if hasattr(tool, 'inputSchema') else {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                    
                    # Sanitize schema for Gemini compatibility
                    sanitized_schema = self._sanitize_json_schema(input_schema)
                    logger.debug(f"Tool {tool.name} - Original schema: {input_schema}")
                    logger.debug(f"Tool {tool.name} - Sanitized schema: {sanitized_schema}")
                    
                    function_decl = FunctionDeclaration(
                        name=tool.name,
                        description=tool.description or f"Tool from {server_name}",
                        parameters=sanitized_schema
                    )
                    self.function_declarations.append(function_decl)
                    
                    logger.info(f"Registered tool: {tool.name} from {server_name}")
                    
            except Exception as e:
                logger.error(f"Failed to register tools from session {i}: {e}", exc_info=True)
        
        logger.info(f"Registered {len(self.tool_registry)} tools total")

    def _sanitize_json_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize JSON schema to be compatible with Gemini function declarations."""
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": []}
        
        # Create a clean copy
        sanitized = {}
        
        # Copy allowed fields for Gemini (exclude JSON Schema specific fields)
        allowed_fields = {"type", "properties", "required", "description", "items", "enum"}
        # Explicitly exclude problematic JSON Schema fields
        excluded_fields = {"additional_properties", "additionalProperties", "$schema", "$id", "$ref", "definitions", "patternProperties", "dependencies"}
        
        for key, value in schema.items():
            if key in allowed_fields and key not in excluded_fields:
                if key == "properties" and isinstance(value, dict):
                    # Recursively sanitize nested properties
                    sanitized[key] = {}
                    for prop_name, prop_schema in value.items():
                        sanitized[key][prop_name] = self._sanitize_json_schema(prop_schema)
                elif key == "items" and isinstance(value, dict):
                    # Sanitize array item schema
                    sanitized[key] = self._sanitize_json_schema(value)
                else:
                    sanitized[key] = value
        
        # Ensure we have required fields
        if "type" not in sanitized:
            sanitized["type"] = "object"
        
        if sanitized["type"] == "object" and "properties" not in sanitized:
            sanitized["properties"] = {}
            
        if sanitized["type"] == "object" and "required" not in sanitized:
            sanitized["required"] = []
        
        return sanitized

    async def _call_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call an MCP tool and return the result."""
        if tool_name not in self.tool_registry:
            error_msg = f"Tool '{tool_name}' not found in registry"
            logger.error(error_msg)
            return {"error": error_msg, "result": None}
        
        tool_info = self.tool_registry[tool_name]
        session = tool_info['session']
        
        # Publish tool request to context manager if available
        call_id = None
        if self.context_manager:
            call_id = self.context_manager.publish_tool_request(tool_name, arguments)
        
        try:
            logger.info(f"Tool invoked: {tool_name}")
            logger.debug(f"Tool arguments: {arguments}")
            
            # Call the MCP tool
            result = await session.call_tool(tool_name, arguments)
            
            logger.info(f"Tool completed: {tool_name}")
            logger.debug(f"Tool result type: {type(result)}")
            
            # Extract serializable content from CallToolResult
            if hasattr(result, 'content'):
                serializable_result = []
                for content_item in result.content:
                    if hasattr(content_item, 'text'):
                        serializable_result.append({"type": "text", "text": content_item.text})
                    else:
                        serializable_result.append(str(content_item))
                final_result = {"error": None, "result": serializable_result}
            else:
                final_result = {"error": None, "result": str(result)}
            
            # Publish tool result to context manager if available
            if self.context_manager and call_id:
                self.context_manager.publish_tool_result(call_id, final_result.get('result'), final_result.get('error'))
                
            return final_result
            
        except Exception as e:
            error_msg = f"Tool '{tool_name}' failed: {str(e)}"
            logger.error(error_msg, exc_info=True)
            final_result = {"error": error_msg, "result": None}
            
            # Publish error result to context manager if available
            if self.context_manager and call_id:
                self.context_manager.publish_tool_result(call_id, final_result.get('result'), final_result.get('error'))
                
            return final_result

    async def prompt(
        self, 
        prompt: str, 
        attachments: Optional[List[Attachment]] = None,
        response_json_schema: Optional[Dict] = None,
        conversation_context: Optional[ConversationHistory] = None
    ) -> str:
        """
        Enhanced prompt method using manual function calling for full conversational control.
        
        Args:
            prompt: The text prompt to send (should be full formatted prompt from conversation history)
            attachments: List of Attachment objects to include
            response_json_schema: JSON schema for response
            conversation_context: Existing conversation context to continue (not used when context_manager is available)
            
        Returns:
            The string response from the model with full tool call context preserved
        """
        try:
            logger.info("Processing prompt with manual MCP tool calling")
            
            # Log available tools
            if self.tool_registry:
                logger.info(f"Available MCP tools: {list(self.tool_registry.keys())}")
            
            # Use context from context_manager if available, otherwise use provided context
            if self.context_manager:
                conversation_context = self.context_manager.get_context()
            elif conversation_context is None:
                conversation_context = ConversationHistory(messages=[])
            
            # Prepare content from conversation history
            from google.genai.types import Part
            contents = []
            
            # Build conversation history for Gemini
            for message in conversation_context.messages:
                for part in message.parts:
                    if part.type == "text":
                        contents.append(Part.from_text(text=part.content))
            
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

            # Build config with function declarations
            config_params = {}
            
            # Add JSON schema if provided
            if response_json_schema:
                config_params.update({
                    "response_mime_type": "application/json",
                    "response_json_schema": response_json_schema
                })
            
            # Add function declarations for manual tool calling
            if self.function_declarations:
                config_params["tools"] = [Tool(function_declarations=self.function_declarations)]
                logger.info(f"Using {len(self.function_declarations)} MCP function declarations")
            
            config = GenerateContentConfig(**config_params) if config_params else None

            # Start conversation loop for multi-turn tool calling
            max_turns = 25  # Prevent infinite loops
            turn = 0
            response_text = ""  # Initialize response_text
            
            while turn < max_turns:
                turn += 1
                logger.debug(f"Conversation turn {turn}")
                
                # Call Gemini with current conversation state
                response = await self.gemini.client.aio.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=contents,
                    config=config
                )
                
                # Check if response contains function calls
                function_calls = []
                response_text = ""  # Reset for each turn
                
                if hasattr(response, 'candidates') and response.candidates:
                    candidate = response.candidates[0]
                    if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                        for part in candidate.content.parts:
                            if hasattr(part, 'function_call') and part.function_call is not None:
                                function_calls.append(part.function_call)
                            elif hasattr(part, 'text') and part.text:
                                response_text += part.text
                
                if not function_calls:
                    # No more function calls, we have the final response
                    logger.info(f"Final response received after {turn} turns")
                    
                    # Note: AI response will be published to context by the caller (rawr.py)
                    return response_text or ""
                
                # Process function calls
                logger.info(f"Processing {len(function_calls)} function calls in turn {turn}")
                
                # Track tool calls in context
                tracked_tool_calls = []
                tracked_tool_results = []
                
                for func_call in function_calls:
                    logger.debug(f"Function call object: {func_call}")
                    logger.debug(f"Function call type: {type(func_call)}")
                    logger.debug(f"Function call attributes: {dir(func_call)}")
                    
                    # Handle different function call formats
                    if hasattr(func_call, 'name'):
                        tool_name = func_call.name
                        arguments = dict(func_call.args) if hasattr(func_call, 'args') else {}
                    elif hasattr(func_call, 'function_name'):
                        tool_name = func_call.function_name
                        arguments = dict(func_call.arguments) if hasattr(func_call, 'arguments') else {}
                    else:
                        logger.error(f"Unknown function call format: {func_call}")
                        continue
                    
                    # Create tool call record
                    tool_call = ToolCall(
                        tool_name=tool_name,
                        tool_id=f"call_{turn}_{tool_name}_{int(datetime.now().timestamp() * 1000)}",
                        parameters=arguments
                    )
                    tracked_tool_calls.append(tool_call)
                    
                    # Execute the tool
                    tool_result = await self._call_mcp_tool(tool_name, arguments)
                    
                    # Create tool result record
                    tool_result_obj = ToolResult(
                        tool_call_id=tool_call.tool_id,
                        result=tool_result.get('result'),
                        error=tool_result.get('error')
                    )
                    tracked_tool_results.append(tool_result_obj)
                    
                    # Add function response as text for next turn (simplified approach)
                    result_text = f"Function {tool_name} returned: {tool_result.get('result', 'No result')}"
                    contents.append(Part.from_text(text=result_text))
                
                # Note: Tool calls and results are now published directly via context_manager in _call_mcp_tool
            
            # If we reach max turns, return what we have
            logger.warning(f"Reached maximum turns ({max_turns}), returning current response")
            final_response = response_text or "Maximum conversation turns reached"
            
            # Note: Final response will be published to context by the caller (rawr.py)
            return final_response
            
        except Exception as e:
            logger.error(f"Error in manual MCP prompt: {e}", exc_info=True)
            # Fallback to regular Gemini prompt without MCP
            logger.info("Falling back to regular Gemini prompt")
            return await self.gemini.prompt(prompt, attachments, response_json_schema)

    async def get_available_tools(self) -> Dict[str, List[str]]:
        """Get list of available tools from tool registry."""
        tools_by_server = {}
        
        for tool_name, tool_info in self.tool_registry.items():
            server_name = tool_info['server_name']
            if server_name not in tools_by_server:
                tools_by_server[server_name] = []
            tools_by_server[server_name].append(tool_name)
                
        return tools_by_server

    async def get_connection_status(self) -> Dict[str, bool]:
        """Get connection status for all configured servers."""
        status = {}
        for i, server in enumerate(self.servers):
            status[server.name] = i < len(self.mcp_sessions)
        return status




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