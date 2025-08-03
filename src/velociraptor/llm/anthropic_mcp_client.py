"""
Anthropic MCP client with AWS Bedrock support.

This module provides MCP-enhanced Anthropic Claude clients that connect to MCP servers
and support tool calling through AWS Bedrock. Defaults to Claude Sonnet 4.

Requires:
- anthropic[bedrock] SDK
- AWS credentials configured 
- Access to Anthropic models in AWS Bedrock console
"""

from contextlib import AsyncExitStack
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
import subprocess
from datetime import datetime
import time
import os
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from velociraptor.models.attachment import Attachment
from velociraptor.models.conversation import (
    ConversationHistory, 
    ToolCall,
    ToolResult
)
from velociraptor.utils.logger import get_logger

# Forward reference for type hints
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from velociraptor.utils.context_manager import ContextManager

logger = get_logger(__name__)

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None  # type: ignore
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic SDK not available. Install with: pip install 'anthropic[bedrock]'")


@dataclass
class MCPServer:
    """Configuration for an MCP server connection."""
    name: str
    container_pattern: str  # Pattern to match container names
    module_path: str
    description: str
    container_name: Optional[str] = None  # Actual resolved container name


class AnthropicClient:
    """Anthropic client using AWS Bedrock."""
    
    def __init__(self, aws_region: str = "us-east-1"):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic SDK is required. Install with: pip install 'anthropic[bedrock]'")
        
        self.aws_region = aws_region
        self.client = None
        self._initialize_client()
    
    def _initialize_client(self) -> None:
        """Initialize Anthropic Bedrock client."""
        # Use Anthropic's built-in Bedrock client
        self.client = anthropic.AsyncAnthropicBedrock(
            aws_region=self.aws_region
        )
        logger.info(f"Initialized Anthropic Bedrock client for region {self.aws_region}")
    
    async def prompt(
        self, 
        prompt: str, 
        attachments: Optional[List[Attachment]] = None,
        response_json_schema: Optional[Dict] = None,
        tools: Optional[List[Dict]] = None,
        model: str = "arn:aws:bedrock:us-east-1:384232296347:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0" #"anthropic.claude-sonnet-4-20250514-v1:0"
    ) -> Dict[str, Any]:
        """
        Submit a prompt to Anthropic Claude.
        
        Args:
            prompt: The text prompt to send
            attachments: List of Attachment objects to include
            response_json_schema: JSON schema for response (not directly supported)
            tools: List of tool definitions for function calling
            model: Model to use
            
        Returns:
            Dict containing response and metadata
        """
        try:
            start_time = time.time()
            logger.info(f"Begin Anthropic prompt")
            
            # Build messages
            messages = [{"role": "user", "content": []}]
            
            # Add text content
            messages[0]["content"].append({
                "type": "text",
                "text": prompt
            })
            
            # Add attachments as images if provided
            if attachments:
                import aiofiles
                import base64
                
                for attachment in attachments:
                    try:
                        async with aiofiles.open(attachment.file_path, 'rb') as f:
                            file_data = await f.read()
                        
                        # Only support images for now
                        if attachment.mime_type.startswith('image/'):
                            messages[0]["content"].append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": attachment.mime_type,
                                    "data": base64.b64encode(file_data).decode()
                                }
                            })
                    except Exception as e:
                        logger.error(f"Failed to read attachment {attachment.file_path}: {e}", exc_info=True)
                        raise
            
            # Build request parameters
            request_params = {
                "model": model,
                "messages": messages,
            }
            
            if tools:
                request_params["tools"] = tools
            
            # Make request using unified client with streaming for extended thinking
            response_content = []
            response_model = None
            response_stop_reason = None
            response_usage = None
            
            async with self.client.messages.stream(**request_params) as stream:
                async for event in stream:
                    if hasattr(event, 'type'):
                        if event.type == "message_start":
                            response_model = event.message.model
                            response_usage = event.message.usage
                        elif event.type == "content_block_start":
                            # Initialize content block
                            if hasattr(event.content_block, 'type'):
                                if event.content_block.type == "text":
                                    response_content.append({"type": "text", "text": ""})
                                elif event.content_block.type == "tool_use":
                                    response_content.append({
                                        "type": "tool_use",
                                        "id": event.content_block.id,
                                        "name": event.content_block.name,
                                        "input": {}
                                    })
                        elif event.type == "content_block_delta":
                            # Handle streaming content - we'll collect it
                            if hasattr(event.delta, 'text'):
                                # Text content
                                if response_content and response_content[-1].get("type") == "text":
                                    response_content[-1]["text"] += event.delta.text
                            elif hasattr(event.delta, 'partial_json'):
                                # Tool use input (streaming JSON)
                                if response_content and response_content[-1].get("type") == "tool_use":
                                    # Accumulate the JSON input
                                    if "partial_input" not in response_content[-1]:
                                        response_content[-1]["partial_input"] = ""
                                    response_content[-1]["partial_input"] += event.delta.partial_json
                        elif event.type == "content_block_stop":
                            # Content block finished - finalize tool use input if needed
                            if response_content and response_content[-1].get("type") == "tool_use":
                                if "partial_input" in response_content[-1]:
                                    # Parse the accumulated JSON
                                    import json
                                    try:
                                        response_content[-1]["input"] = json.loads(response_content[-1]["partial_input"])
                                        del response_content[-1]["partial_input"]
                                    except json.JSONDecodeError as e:
                                        logger.error(f"Failed to parse tool input JSON: {e}")
                                        response_content[-1]["input"] = {}
                        elif event.type == "message_delta":
                            response_stop_reason = event.delta.stop_reason
                        elif event.type == "message_stop":
                            # Message finished
                            break
            
            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"End Anthropic prompt ({processing_time_ms}ms)")
            
            return {
                "content": response_content,
                "model": response_model,
                "stop_reason": response_stop_reason,
                "usage": response_usage.model_dump() if response_usage else None
            }
            
        except Exception as e:
            logger.error(f"Error with Anthropic prompt: {e}", exc_info=True)
            raise


class MCPAnthropicClient:
    """MCP-enhanced Anthropic client using manual function calling for full conversational control."""

    def __init__(self, context_manager: Optional['ContextManager'] = None, aws_region: str = "us-east-1"):
        self.anthropic_client = AnthropicClient(aws_region=aws_region)
        self.exit_stack: Optional[AsyncExitStack] = None
        self.mcp_sessions: List[ClientSession] = []
        self.context_manager = context_manager
        
        # Tool registry mapping tool names to MCP sessions and metadata
        self.tool_registry: Dict[str, Dict[str, Any]] = {}
        
        # Tool definitions for Anthropic function calling
        self.tool_definitions: List[Dict[str, Any]] = []
        
        # Configure MCP servers from docker-compose.yml (same as Gemini client)
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
        
        # Add recursive server - depth limiting is now handled by the tool itself
        self.servers.append(
            MCPServer(
                name="recursive_mcp",
                container_pattern="recursive-mcp",
                module_path="velociraptor.mcp.recursive_mcp",
                description="Recursive query processing with depth limiting for complex multi-step analysis"
            )
        )

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
            raise RuntimeError("MCPAnthropicClient must be used as async context manager")
            
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
        self.tool_definitions.clear()
        
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
                    
                    # Create tool definition for Anthropic with sanitized schema
                    input_schema = tool.inputSchema if hasattr(tool, 'inputSchema') else {
                        "type": "object",
                        "properties": {},
                        "required": []
                    }
                    
                    # Sanitize schema for Anthropic compatibility
                    sanitized_schema = self._sanitize_json_schema(input_schema)
                    logger.debug(f"Tool {tool.name} - Original schema: {input_schema}")
                    logger.debug(f"Tool {tool.name} - Sanitized schema: {sanitized_schema}")
                    
                    tool_def = {
                        "name": tool.name,
                        "description": tool.description or f"Tool from {server_name}",
                        "input_schema": sanitized_schema
                    }
                    self.tool_definitions.append(tool_def)
                    
                    logger.info(f"Registered tool: {tool.name} from {server_name}")
                    
            except Exception as e:
                logger.error(f"Failed to register tools from session {i}: {e}", exc_info=True)
        
        logger.info(f"Registered {len(self.tool_registry)} tools total")

    def _sanitize_json_schema(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize JSON schema to be compatible with Anthropic tool definitions."""
        if not isinstance(schema, dict):
            return {"type": "object", "properties": {}, "required": []}
        
        # Create a clean copy
        sanitized = {}
        
        # Copy allowed fields for Anthropic
        allowed_fields = {"type", "properties", "required", "description", "items", "enum"}
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

    async def _call_anthropic_with_messages(
        self,
        messages: List[Dict[str, Any]],
        attachments: Optional[List[Attachment]] = None,
        tools: Optional[List[Dict]] = None
    ) -> Dict[str, Any]:
        """Call Anthropic with a list of conversation messages using streaming."""
        # Build request parameters
        request_params = {
            "model": "arn:aws:bedrock:us-east-1:384232296347:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0",
            "max_tokens": 20000,
            "messages": messages,
            # "thinking": {
            #     "type": "enabled",
            #     "budget_tokens": 10000
            # }
        }

        if tools:
            request_params["tools"] = tools
        
        # Use streaming to handle extended thinking
        response_content = []
        response_model = None
        response_stop_reason = None
        response_usage = None
        
        async with self.anthropic_client.client.messages.stream(**request_params) as stream:
            async for event in stream:
                if hasattr(event, 'type'):
                    if event.type == "message_start":
                        response_model = event.message.model
                        response_usage = event.message.usage
                    elif event.type == "content_block_start":
                        # Initialize content block
                        if hasattr(event.content_block, 'type'):
                            if event.content_block.type == "text":
                                response_content.append({"type": "text", "text": ""})
                            elif event.content_block.type == "thinking":
                                response_content.append({"type": "thinking", "thinking": "", "signature": ""})
                            elif event.content_block.type == "tool_use":
                                response_content.append({
                                    "type": "tool_use",
                                    "id": event.content_block.id,
                                    "name": event.content_block.name,
                                    "input": {}
                                })
                    elif event.type == "content_block_delta":
                        # Handle streaming content
                        if hasattr(event.delta, 'text'):
                            # Text content or thinking content
                            if response_content and response_content[-1].get("type") == "text":
                                response_content[-1]["text"] += event.delta.text
                            elif response_content and response_content[-1].get("type") == "thinking":
                                response_content[-1]["thinking"] += event.delta.text
                        elif hasattr(event.delta, 'partial_json'):
                            # Tool use input (streaming JSON)
                            if response_content and response_content[-1].get("type") == "tool_use":
                                # Accumulate the JSON input
                                if "partial_input" not in response_content[-1]:
                                    response_content[-1]["partial_input"] = ""
                                response_content[-1]["partial_input"] += event.delta.partial_json
                        elif hasattr(event.delta, 'type') and event.delta.type == "signature_delta":
                            # Handle signature delta for thinking blocks
                            if response_content and response_content[-1].get("type") == "thinking" and hasattr(event.delta, 'signature'):
                                response_content[-1]["signature"] = event.delta.signature
                    elif event.type == "content_block_stop":
                        # Content block finished - finalize tool use input if needed
                        if response_content and response_content[-1].get("type") == "tool_use":
                            if "partial_input" in response_content[-1]:
                                # Parse the accumulated JSON
                                import json
                                try:
                                    response_content[-1]["input"] = json.loads(response_content[-1]["partial_input"])
                                    del response_content[-1]["partial_input"]
                                except json.JSONDecodeError as e:
                                    logger.error(f"Failed to parse tool input JSON: {e}")
                                    response_content[-1]["input"] = {}
                                    # Still remove partial_input even on error
                                    del response_content[-1]["partial_input"]
                    elif event.type == "message_delta":
                        response_stop_reason = event.delta.stop_reason
                    elif event.type == "message_stop":
                        # Message finished
                        break
        
        # Final cleanup: ensure no partial_input fields remain in tool_use blocks
        for content_item in response_content:
            if content_item.get("type") == "tool_use" and "partial_input" in content_item:
                import json
                try:
                    content_item["input"] = json.loads(content_item["partial_input"])
                except json.JSONDecodeError:
                    content_item["input"] = {}
                del content_item["partial_input"]
        
        return {
            "content": response_content,
            "model": response_model,
            "stop_reason": response_stop_reason,
            "usage": response_usage.model_dump() if response_usage else None
        }

    async def prompt(
        self, 
        prompt: str, 
        attachments: Optional[List[Attachment]] = None,
        conversation_context: Optional[ConversationHistory] = None
    ) -> str:
        """
        Enhanced prompt method using manual function calling for full conversational control.
        
        Args:
            prompt: The text prompt to send (should be full formatted prompt from conversation history)
            attachments: List of Attachment objects to include
            conversation_context: Existing conversation context to continue (not used when context_manager is available)
            
        Returns:
            The string response from the model with full tool call context preserved
        """
        try:
            logger.info("Processing prompt with manual MCP tool calling")
            
            # Log available tools
            if self.tool_registry:
                logger.info(f"Available MCP tools: {list(self.tool_registry.keys())}")
            
            # Use context from context_manager if available
            if self.context_manager:
                self.context_manager.get_context()
            # Note: conversation_context parameter is available but not used in current implementation
            
            # Start conversation loop for multi-turn tool calling
            max_turns = 25  # Prevent infinite loops
            turn = 0
            response_text = ""
            
            # Initialize conversation messages
            conversation_messages = [{"role": "user", "content": prompt}]
            
            while turn < max_turns:
                turn += 1
                logger.debug(f"Conversation turn {turn}")
                
                # Call Anthropic with current conversation messages
                # We need to modify the base client to accept messages directly
                response = await self._call_anthropic_with_messages(
                    messages=conversation_messages,
                    attachments=attachments if turn == 1 else None,
                    tools=self.tool_definitions if self.tool_definitions else None
                )
                
                # Check if response contains tool calls
                tool_calls = []
                response_text = ""
                thinking_text = ""
                
                if "content" in response:
                    for content_item in response["content"]:
                        if isinstance(content_item, dict):
                            if content_item.get("type") == "text":
                                response_text += content_item.get("text", "")
                            elif content_item.get("type") == "thinking":
                                thinking_text += content_item.get("content", "")
                            elif content_item.get("type") == "tool_use":
                                tool_calls.append(content_item)
                        else:
                            # Handle case where content_item is not a dict (e.g., Anthropic TextBlock)
                            if hasattr(content_item, 'type') and content_item.type == "text":
                                response_text += getattr(content_item, 'text', "")
                            elif hasattr(content_item, 'type') and content_item.type == "thinking":
                                thinking_text += getattr(content_item, 'content', "")
                            elif hasattr(content_item, 'type') and content_item.type == "tool_use":
                                tool_calls.append({
                                    "type": "tool_use",
                                    "id": getattr(content_item, 'id', ''),
                                    "name": getattr(content_item, 'name', ''),
                                    "input": getattr(content_item, 'input', {})
                                })

                logger.info(f"Found {len(tool_calls)} tool calls")
                
                if not tool_calls:
                    # No more tool calls, we have the final response
                    logger.info(f"Final response received after {turn} turns")
                    return response_text or ""
                
                # Add assistant's response (with proper thinking block ordering) to conversation
                assistant_content = []
                
                # Extract thinking, text, and tool_use blocks from response
                thinking_blocks = []
                text_blocks = []
                tool_use_blocks = []
                
                for content_item in response.get("content", []):
                    if isinstance(content_item, dict):
                        if content_item.get("type") == "thinking":
                            thinking_blocks.append(content_item)
                        elif content_item.get("type") == "text":
                            text_blocks.append(content_item)
                        elif content_item.get("type") == "tool_use":
                            tool_use_blocks.append(content_item)
                
                # Build assistant content in correct order: thinking first, then text, then tool_use
                assistant_content.extend(thinking_blocks)
                assistant_content.extend(text_blocks) 
                assistant_content.extend(tool_use_blocks)
                
                conversation_messages.append({"role": "assistant", "content": assistant_content})
                
                # Publish thinking content to context manager if available
                if self.context_manager and thinking_blocks:
                    full_thinking = ""
                    for thinking_block in thinking_blocks:
                        full_thinking += thinking_block.get("content", "")
                    if full_thinking:
                        # For now, log the thinking - we may want to add a dedicated method later
                        logger.info(f"Claude's thinking: {full_thinking[:200]}...")
                        # You could add: self.context_manager.publish_thinking(full_thinking)
                
                # Process tool calls and add results  
                logger.info(f"Processing {len(tool_use_blocks)} tool calls in turn {turn}")
                
                # Track tool calls in context
                tracked_tool_calls = []
                tracked_tool_results = []
                tool_result_content = []
                
                for tool_call in tool_use_blocks:
                    tool_name = tool_call.get("name", "")
                    tool_id = tool_call.get("id", f"call_{turn}_{tool_name}_{int(datetime.now().timestamp() * 1000)}")
                    arguments = tool_call.get("input", {})
                    
                    # Create tool call record
                    tool_call_obj = ToolCall(
                        tool_name=tool_name,
                        tool_id=tool_id,
                        parameters=arguments
                    )
                    tracked_tool_calls.append(tool_call_obj)
                    
                    # Execute the tool
                    tool_result = await self._call_mcp_tool(tool_name, arguments)
                    
                    # Write context to separate file for recursive calls
                    if tool_name == "recursive_query" and arguments.get("depth", 0) > 0:
                        await self._write_recursive_context(arguments.get("depth", 0), conversation_messages, tool_result)
                    
                    # Create tool result record
                    tool_result_obj = ToolResult(
                        tool_call_id=tool_id,
                        result=tool_result.get('result'),
                        error=tool_result.get('error')
                    )
                    tracked_tool_results.append(tool_result_obj)
                    
                    # Add tool result to conversation
                    result_content = []
                    has_content = False
                    
                    if tool_result.get('result'):
                        if isinstance(tool_result.get('result'), list):
                            # Handle list of result items (typical MCP format)
                            for item in tool_result.get('result'):
                                if isinstance(item, dict):
                                    if item.get('type') == 'text':
                                        result_content.append({
                                            "type": "text",
                                            "text": item.get('text', '')
                                        })
                                        has_content = True
                                    elif item.get('type') == 'image':
                                        # Handle ImageContent - convert to image_url format
                                        base64_data = item.get('data', '')
                                        mime_type = item.get('mimeType', 'image/jpeg')
                                        if base64_data:
                                            result_content.append({
                                                "type": "image_url",
                                                "image_url": {"url": f"data:{mime_type};base64,{base64_data}"}
                                            })
                                            has_content = True
                                else:
                                    # Fallback to text for non-dict items
                                    result_content.append({
                                        "type": "text", 
                                        "text": str(item)
                                    })
                                    has_content = True
                        else:
                            # Single result item - convert to text
                            result_content.append({
                                "type": "text",
                                "text": str(tool_result.get('result'))
                            })
                            has_content = True
                    
                    if tool_result.get('error'):
                        error_text = f"Error: {tool_result.get('error')}"
                        if has_content:
                            # Add error as additional text content
                            result_content.append({
                                "type": "text",
                                "text": error_text
                            })
                        else:
                            # Only error, make it the main content
                            result_content.append({
                                "type": "text", 
                                "text": error_text
                            })
                    
                    # Fallback if no content
                    if not result_content:
                        result_content.append({
                            "type": "text",
                            "text": "No result"
                        })
                    
                    tool_result_content.append({
                        "type": "tool_result",
                        "tool_use_id": tool_id,
                        "content": result_content
                    })
                
                # Add tool results as user message
                conversation_messages.append({"role": "user", "content": tool_result_content})
            
            # If we reach max turns, return what we have
            logger.warning(f"Reached maximum turns ({max_turns}), returning current response")
            return response_text or "Maximum conversation turns reached"
            
        except Exception as e:
            logger.error(f"Error in manual MCP prompt: {e}", exc_info=True)
            raise

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
    
    async def _write_recursive_context(self, depth: int, conversation_messages: List[Dict[str, Any]], tool_result: Dict[str, Any]) -> None:
        """Write context to a separate file for recursive calls to isolate context."""
        try:
            try:
                import aiofiles
            except ImportError:
                logger.warning("aiofiles not available, using synchronous file write for recursive context")
                # Fallback to synchronous write
                context_data = {
                    "depth": depth,
                    "timestamp": datetime.now().isoformat(),
                    "conversation_messages": conversation_messages,
                    "tool_result": tool_result,
                    "metadata": {
                        "type": "recursive_context",
                        "version": "1.0"
                    }
                }
                context_filename = f".context.{depth}.json"
                with open(context_filename, 'w') as f:
                    f.write(json.dumps(context_data, indent=2, default=str))
                logger.info(f"Wrote recursive context to {context_filename} for depth {depth}")
                return
            
            # Create context data
            context_data = {
                "depth": depth,
                "timestamp": datetime.now().isoformat(),
                "conversation_messages": conversation_messages,
                "tool_result": tool_result,
                "metadata": {
                    "type": "recursive_context",
                    "version": "1.0"
                }
            }
            
            # Write to .context.{depth}.json file
            context_filename = f".context.{depth}.json"
            
            async with aiofiles.open(context_filename, 'w') as f:
                await f.write(json.dumps(context_data, indent=2, default=str))
            
            logger.info(f"Wrote recursive context to {context_filename} for depth {depth}")
            
        except Exception as e:
            logger.error(f"Failed to write recursive context: {e}", exc_info=True)


# Enhanced Anthropic class that includes MCP support
class AnthropicWithMCP(AnthropicClient):
    """Extended Anthropic class with built-in MCP support."""
    
    def __init__(self, aws_region: str = "us-east-1"):
        super().__init__(aws_region=aws_region)
        self.mcp_client: Optional[MCPAnthropicClient] = None
    
    async def enable_mcp(self) -> None:
        """Enable MCP support by connecting to MCP servers."""
        if not self.mcp_client:
            self.mcp_client = MCPAnthropicClient(
                aws_region=self.aws_region
            )
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
        retry_count: int = 0,
        **kwargs
    ) -> str:
        """
        Enhanced prompt method with MCP support.
        
        Args:
            prompt: The text prompt to send
            attachments: List of Attachment objects to include
            retry_count: Current retry attempt (internal use)
            **kwargs: Additional arguments passed to base prompt method
            
        Returns:
            The string response from the model
        """
        # Use MCP if enabled
        if self.mcp_client:
            try:
                return await self.mcp_client.prompt(prompt, attachments)
            except Exception as e:
                logger.warning(f"MCP prompt failed, falling back to regular prompt: {e}")
        
        # Fallback to regular prompt
        response = await super().prompt(prompt, attachments, **kwargs)
        if isinstance(response, dict) and "content" in response:
            # Extract text from response content
            text_parts = []
            for content_item in response["content"]:
                if isinstance(content_item, dict) and content_item.get("type") == "text":
                    text_parts.append(content_item.get("text", ""))
            return "\n".join(text_parts)
        return str(response)


# Convenience functions
async def prompt_with_mcp(
    prompt: str, 
    attachments: Optional[List[Attachment]] = None,
    aws_region: str = "us-east-1"
) -> str:
    """
    Convenience function to prompt with MCP tool support.
    Creates a new client instance, processes the prompt, and cleans up.
    """
    async with MCPAnthropicClient(aws_region=aws_region) as client:
        return await client.prompt(prompt, attachments)


async def create_mcp_enabled_anthropic(aws_region: str = "us-east-1") -> AnthropicWithMCP:
    """
    Create an Anthropic instance with MCP support enabled.
    Remember to call disable_mcp() when done to cleanup connections.
    """
    anthropic_client = AnthropicWithMCP(aws_region=aws_region)
    await anthropic_client.enable_mcp()
    return anthropic_client