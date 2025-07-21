import asyncio
import re
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ServerCapabilities

from velociraptor.db.neo4j import Neo4jDb
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)

server = Server("neo4j-fulltext-search")
neo4j_db = Neo4jDb()

# Allowed CALL patterns (case-insensitive)
ALLOWED_PATTERNS = [
    r'^\s*CALL\s+db\.index\.fulltext\.queryNodes\s*\(',
    r'^\s*CALL\s+db\.index\.fulltext\.queryRelationships\s*\('
]


def is_query_allowed(query: str) -> bool:
    """
    Validate that the query only contains allowed CALL operations.
    
    Args:
        query: The Cypher query to validate
        
    Returns:
        True if query is allowed, False otherwise
    """
    query = query.strip()
    
    # Check if query matches any allowed pattern
    for pattern in ALLOWED_PATTERNS:
        if re.match(pattern, query, re.IGNORECASE):
            return True
    
    return False


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools for Neo4j full-text search."""
    return [
        Tool(
            name="neo4j_fulltext_search",
            description="Execute Neo4j full-text search queries. Only CALL db.index.fulltext.queryNodes() and CALL db.index.fulltext.queryRelationships() are permitted.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The Cypher query to execute. Must be a CALL db.index.fulltext.queryNodes() or CALL db.index.fulltext.queryRelationships() query."
                    }
                },
                "required": ["query"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls for Neo4j full-text search."""
    if name != "neo4j_fulltext_search":
        raise ValueError(f"Unknown tool: {name}")
    
    query = arguments.get("query")
    
    if not query:
        raise ValueError("Query parameter is required")
    
    # Validate query is allowed
    if not is_query_allowed(query):
        error_msg = "Query not allowed. Only CALL db.index.fulltext.queryNodes() and CALL db.index.fulltext.queryRelationships() are permitted."
        logger.warning(f"Rejected query: {query}")
        return [
            TextContent(
                type="text",
                text=error_msg
            )
        ]
    
    try:
        logger.info(f"Executing full-text search query: {query[:100]}...")
        
        # Execute the query
        async with neo4j_db.driver.session() as session:
            result = await session.run(query)
            records = await result.data()
        
        # Return results as JSON
        import json
        
        if not records:
            response_text = json.dumps({"message": "No results found", "records": []})
        else:
            # Convert Neo4j nodes/relationships to serializable format
            serializable_records = []
            for record in records:
                serializable_record = {}
                for key, value in record.items():
                    if hasattr(value, '__dict__'):
                        # Handle Neo4j Node/Relationship objects
                        if hasattr(value, 'labels'):  # Node
                            serializable_record[key] = {
                                'properties': dict(value),
                                'labels': list(value.labels),
                                'element_id': value.element_id if hasattr(value, 'element_id') else None
                            }
                        elif hasattr(value, 'type'):  # Relationship
                            serializable_record[key] = {
                                'properties': dict(value),
                                'type': value.type,
                                'element_id': value.element_id if hasattr(value, 'element_id') else None
                            }
                        else:
                            serializable_record[key] = dict(value) if hasattr(value, '__iter__') else str(value)
                    else:
                        serializable_record[key] = value
                
                serializable_records.append(serializable_record)
            
            response_text = json.dumps({"records": serializable_records}, indent=2)
        
        logger.info(f"Full-text search returned {len(records)} results")
        return [
            TextContent(
                type="text",
                text=response_text
            )
        ]
        
    except Exception as e:
        logger.error(f"Error executing full-text search: {e}", exc_info=True)
        return [
            TextContent(
                type="text", 
                text=f"Error executing full-text search: {str(e)}"
            )
        ]


async def main():
    """Run the MCP server."""
    logger.info("Starting neo4j-fulltext-search MCP server")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, 
            write_stream, 
            InitializationOptions(
                server_name="neo4j-fulltext-search",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())