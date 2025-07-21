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
        
        # Return results directly as JSON
        import json
        
        if not results:
            response_text = json.dumps({"message": "No matching documents found", "results": []})
        else:
            # Convert Neo4j nodes to serializable format
            serializable_results = []
            for result in results:
                parent = result['parent']
                score = result['score']
                
                # Convert node to dict
                node_dict = dict(parent)
                node_dict['_id'] = parent.id if hasattr(parent, 'id') else None
                node_dict['_labels'] = list(parent.labels) if hasattr(parent, 'labels') else []
                
                serializable_results.append({
                    'parent': node_dict,
                    'score': score
                })
            
            response_text = json.dumps({"results": serializable_results}, indent=2)
        
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