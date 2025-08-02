from contextlib import AsyncExitStack
from typing import Optional, Dict, List
from dataclasses import dataclass
import subprocess

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from google.genai.types import GenerateContentConfig

from velociraptor.llm.gemini import Gemini
from velociraptor.models.attachment import Attachment
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
                description="Neo4j Cypher queries for graph database operations"
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