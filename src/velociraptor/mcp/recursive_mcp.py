"""
Recursive MCP Server with depth limiting.

This server can call itself recursively to answer complex questions by breaking them down
into smaller sub-questions. Depth limiting is handled through tool call parameters.
"""

import asyncio
from typing import Any
from datetime import datetime

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ServerCapabilities

from velociraptor.llm.anthropic_mcp_client import MCPAnthropicClient
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)

MAX_RECURSION_DEPTH = 3

server = Server("recursive-mcp")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools for recursive questioning."""
    return [
        Tool(
            name="recursive_query",
            description="Ask a question that can be answered by breaking it down recursively into smaller sub-questions. Useful for complex analysis tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "The question to answer recursively"
                    },
                    "context": {
                        "type": "string", 
                        "description": "Additional context for the question (optional)",
                        "default": ""
                    },
                    "depth": {
                        "type": "integer",
                        "description": "Current recursion depth (0 = top level, increases with each recursive call)",
                        "default": 0,
                        "minimum": 0,
                        "maximum": MAX_RECURSION_DEPTH
                    }
                },
                "required": ["question"]
            }
        ),
        Tool(
            name="get_recursion_status",
            description="Get current recursion depth and status information",
            inputSchema={
                "type": "object",
                "properties": {
                    "depth": {
                        "type": "integer",
                        "description": "Current depth to check",
                        "default": 0
                    }
                },
                "required": []
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls for recursive questioning."""
    
    if name == "get_recursion_status":
        current_depth = arguments.get("depth", 0)
        can_recurse = current_depth < MAX_RECURSION_DEPTH
        
        status = {
            "current_depth": current_depth,
            "max_depth": MAX_RECURSION_DEPTH,
            "can_recurse": can_recurse,
            "timestamp": datetime.now().isoformat()
        }
        
        import json
        return [
            TextContent(
                type="text",
                text=json.dumps(status, indent=2)
            )
        ]
    
    elif name == "recursive_query":
        question = arguments.get("question")
        context = arguments.get("context", "")
        current_depth = arguments.get("depth", 0)
        
        if not question:
            return [
                TextContent(
                    type="text",
                    text="Error: Question parameter is required"
                )
            ]
        
        # The depth we'll operate at is current_depth + 1
        operating_depth = current_depth + 1
        
        logger.info(f"Processing recursive query: received depth {current_depth}, operating at depth {operating_depth}: {question[:100]}...")
        
        # Check if we've reached max depth
        if operating_depth > MAX_RECURSION_DEPTH:
            return [
                TextContent(
                    type="text",
                    text=f"Maximum recursion depth ({MAX_RECURSION_DEPTH}) reached. Cannot process deeper recursive queries."
                )
            ]
        
        try:
            logger.info(f"Making recursive call at depth {operating_depth}")
            
            # Create MCP client for recursive call
            mcp_client = MCPAnthropicClient()
            
            async with mcp_client:
                # Build prompt for recursive analysis that includes recursive_query calls with incremented depth
                system_context = f"""You are operating at recursion depth {operating_depth} of {MAX_RECURSION_DEPTH}.
Your role is to answer complex questions by breaking them down into smaller parts.

Current question: {question}
{f"Additional context: {context}" if context else ""}

You have access to various MCP tools including:
- recursive_query: Use this to break down complex sub-questions
- semantic_search: For finding relevant information
- Neo4j queries for graph-based analysis  
- Page fetching for retrieving specific content
- Full-text search capabilities

CRITICAL: If you need to use recursive_query for sub-questions, you MUST pass depth={operating_depth} as a parameter. This is mandatory for depth tracking.

Example: recursive_query(question="your sub-question", depth={operating_depth})

Break this question down into smaller components and use available tools to gather information systematically. Provide a comprehensive answer based on your analysis.

Important: You are currently at depth {operating_depth}/{MAX_RECURSION_DEPTH}. Any recursive_query calls must use depth={operating_depth}."""

                # Make the recursive call
                response = await mcp_client.prompt(system_context)
                
                logger.info(f"Completed recursive query at depth {operating_depth}")
                
                return [
                    TextContent(
                        type="text",
                        text=f"[Recursion depth {operating_depth}]\n\n{response}"
                    )
                ]
                
        except Exception as e:
            logger.error(f"Error in recursive query at depth {operating_depth}: {e}", exc_info=True)
            return [
                TextContent(
                    type="text",
                    text=f"Error processing recursive query: {str(e)}"
                )
            ]
    
    else:
        raise ValueError(f"Unknown tool: {name}")


async def main():
    """Run the recursive MCP server."""
    logger.info("Starting recursive MCP server with parameter-based depth limiting")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="recursive-mcp",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())