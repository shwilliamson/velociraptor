import asyncio
import base64
import os
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, ServerCapabilities

from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)

server = Server("page-fetch")


def translate_host_to_container_path(host_path: str) -> str:
    """
    Translate a host file path to the corresponding container path.
    
    Args:
        host_path: The file path on the host system
        
    Returns:
        The corresponding path inside the container
    """
    host_path_obj = Path(host_path)
    
    # Find the documents_split part in the path
    parts = host_path_obj.parts
    try:
        # Find where documents_split appears in the path
        docs_split_index = None
        for i, part in enumerate(parts):
            if part == "documents_split":
                docs_split_index = i
                break
        
        if docs_split_index is None:
            raise ValueError("Path does not contain documents_split directory")
        
        # Get everything from documents_split onwards
        remaining_parts = parts[docs_split_index:]
        
        # Construct container path: /app/files/documents_split/...
        container_path = Path("/app/files") / Path(*remaining_parts)
        return str(container_path)
        
    except Exception as e:
        raise ValueError(f"Cannot translate path {host_path}: {e}")


def is_safe_path(host_path: str) -> bool:
    """
    Validate that the host file path is within the allowed directory.
    
    Args:
        host_path: The file path on the host to validate
        
    Returns:
        True if path is safe, False otherwise
    """
    try:
        # Convert to absolute path and resolve any '..' components
        abs_path = Path(host_path).resolve()
        
        # Check if path contains the required directory structure
        path_str = str(abs_path)
        if "files/documents_split" not in path_str:
            return False
            
        # Check if path contains 'pages' directory
        if "pages" not in abs_path.parts:
            return False
            
        # Check if it's a JPG file
        if abs_path.suffix.lower() != ".jpg":
            return False
            
        return True
        
    except Exception:
        return False


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    """List available tools for page image fetching."""
    return [
        Tool(
            name="fetch_page_image",
            description="Fetch a page image from the documents_split/*/pages folder and return it as base64",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Full path to the JPG file within files/documents_split/*/pages folder"
                    }
                },
                "required": ["file_path"]
            }
        )
    ]


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls for page image fetching."""
    if name != "fetch_page_image":
        raise ValueError(f"Unknown tool: {name}")
    
    file_path = arguments.get("file_path")
    
    if not file_path:
        raise ValueError("file_path parameter is required")
    
    try:
        logger.info(f"Fetching page image: {file_path}")
        
        # Validate the host path is safe
        if not is_safe_path(file_path):
            error_msg = (
                f"Invalid file path: {file_path}. "
                "Path must be within files/documents_split/*/pages/ and be a .jpg file"
            )
            logger.warning(error_msg)
            return [
                TextContent(
                    type="text",
                    text=f"Error: {error_msg}"
                )
            ]
        
        # Translate host path to container path
        try:
            container_path = translate_host_to_container_path(file_path)
            logger.info(f"Translated {file_path} to container path: {container_path}")
        except ValueError as e:
            error_msg = f"Path translation error: {e}"
            logger.warning(error_msg)
            return [
                TextContent(
                    type="text",
                    text=f"Error: {error_msg}"
                )
            ]
        
        # Check if file exists at container path
        container_path_obj = Path(container_path)
        if not container_path_obj.exists():
            error_msg = f"File not found: {file_path} (container path: {container_path})"
            logger.warning(error_msg)
            return [
                TextContent(
                    type="text",
                    text=f"Error: {error_msg}"
                )
            ]
        
        if not container_path_obj.is_file():
            error_msg = f"Path is not a file: {file_path} (container path: {container_path})"
            logger.warning(error_msg)
            return [
                TextContent(
                    type="text",
                    text=f"Error: {error_msg}"
                )
            ]
        
        # Read and encode the image file
        with open(container_path_obj, "rb") as f:
            image_data = f.read()
        
        base64_data = base64.b64encode(image_data).decode('utf-8')
        
        logger.info(f"Successfully fetched image: {file_path} ({len(image_data)} bytes)")
        
        return [
            TextContent(
                type="text",
                text=base64_data
            )
        ]
        
    except Exception as e:
        logger.error(f"Error fetching page image: {e}", exc_info=True)
        return [
            TextContent(
                type="text", 
                text=f"Error fetching page image: {str(e)}"
            )
        ]


async def main():
    """Run the MCP server."""
    logger.info("Starting page-fetch MCP server")
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, 
            write_stream, 
            InitializationOptions(
                server_name="page-fetch",
                server_version="1.0.0",
                capabilities=ServerCapabilities(
                    tools={},
                ),
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())