import asyncio
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ServerCapabilities

from velociraptor.llm.gemini import Gemini
from velociraptor.db.neo4j import Neo4jDb
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)

server = Server("semantic-search")
gemini_client = Gemini()
neo4j_db = Neo4jDb()


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools for semantic search."""
    return [
        Tool(
            name="semantic_search",
            description="Perform semantic search by embedding a text query and finding similar document chunks",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The text query to search for"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls for semantic search."""
    if name != "semantic_search":
        raise ValueError(f"Unknown tool: {name}")
    
    query = arguments.get("query")
    limit = arguments.get("limit", 10)
    
    if not query:
        raise ValueError("Query parameter is required")
    
    try:
        logger.info(f"Performing semantic search for: {query[:100]}...")
        
        # Generate embedding for the query
        chunks = []
        async for chunk in gemini_client.embed([query]):
            chunks.append(chunk)
        
        if not chunks:
            raise ValueError("Failed to generate embedding for query")
        
        embedding = chunks[0].embedding
        
        # Perform semantic search in Neo4j
        results = await neo4j_db.semantic_search(embedding, limit)
        
        # Format results as readable text
        if not results:
            response_text = "No matching documents found."
        else:
            response_parts = []
            for i, result in enumerate(results, 1):
                response_parts.append(f"Result {i} (Score: {result['score']:.4f}):")
                response_parts.append(f"Text: {result['text']}")
                response_parts.append(f"Chunk ID: {result['chunk_id']}")
                response_parts.append(f"Parent: {result['parent_labels']} - {result['parent_id']}")
                response_parts.append("")  # Empty line between results
            
            response_text = "\n".join(response_parts)
        
        return [
            TextContent(
                type="text",
                text=response_text
            )
        ]
        
    except Exception as e:
        logger.error(f"Error performing semantic search: {e}", exc_info=True)
        return [
            TextContent(
                type="text", 
                text=f"Error performing semantic search: {str(e)}"
            )
        ]


async def main():
    """Run the MCP server."""
    logger.info("Starting semantic-search MCP server")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, 
            write_stream, 
            InitializationOptions(
                server_name="semantic-search",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())