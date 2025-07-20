import asyncio
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from velociraptor.llm.gemini import Gemini
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)

server = Server("embed-query")
gemini_client = Gemini()


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools for embedding queries."""
    return [
        Tool(
            name="embed_query",
            description="Embed a text query using Gemini's embedding model for vector similarity search",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The text query to embed"
                    }
                },
                "required": ["query"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls for embedding queries."""
    if name != "embed_query":
        raise ValueError(f"Unknown tool: {name}")
    
    query = arguments.get("query")
    if not query:
        raise ValueError("Query parameter is required")
    
    try:
        logger.info(f"Embedding query: {query[:100]}...")
        
        # Use the Gemini embed method to generate embedding for the query
        chunks = []
        async for chunk in gemini_client.embed([query]):
            chunks.append(chunk)
        
        if not chunks:
            raise ValueError("Failed to generate embedding for query")
        
        # Return the embedding vector
        embedding = chunks[0].embedding
        
        return [
            TextContent(
                type="text",
                text=str(embedding)
            )
        ]
        
    except Exception as e:
        logger.error(f"Error embedding query: {e}", exc_info=True)
        return [
            TextContent(
                type="text", 
                text=f"Error embedding query: {str(e)}"
            )
        ]


async def main():
    """Run the MCP server."""
    logger.info("Starting embed-query MCP server")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, 
            write_stream, 
            InitializationOptions(
                server_name="embed-query",
                server_version="1.0.0",
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities=None,
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())