from dotenv import load_dotenv
load_dotenv()

import asyncio
from pathlib import Path
from typing import Optional

from velociraptor.mcp.mcp_client import MCPGeminiClient
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)


async def rawr(prompt: str, continue_conversation: bool = False) -> str:
    """
    Generate a response using Gemini LLM with MCP tool support.
    
    Args:
        prompt: The user prompt to send to the LLM
        continue_conversation: If True, don't prepend system prompt (assumes it's already in context)
        
    Returns:
        The LLM response string
        
    Raises:
        Exception: If there's an error during processing
    """
    try:
        # Load system prompt unless continuing conversation
        if not continue_conversation:
            system_prompt_path = Path(__file__).parent.parent / "prompts" / "mcp_client_system_prompt.md"
            
            try:
                with open(system_prompt_path, 'r', encoding='utf-8') as f:
                    system_prompt = f.read()
                
                # Prepend system prompt to user prompt
                full_prompt = f"{system_prompt}\n\n---\n\n{prompt}"
            except FileNotFoundError:
                logger.warning(f"System prompt file not found at {system_prompt_path}, using prompt as-is")
                full_prompt = prompt
            except Exception as e:
                logger.error(f"Error reading system prompt: {e}", exc_info=True)
                full_prompt = prompt
        else:
            full_prompt = prompt

        # Use MCP-enabled Gemini client
        async with MCPGeminiClient() as client:
            logger.info("Processing prompt with MCP-enabled Gemini")
            response = await client.prompt(full_prompt)
            logger.info("Successfully generated response")
            return response
            
    except Exception as e:
        logger.error(f"Error in rawr function: {e}", exc_info=True)
        raise