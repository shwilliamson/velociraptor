from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

from velociraptor.llm.gemini_mcp_client import MCPGeminiClient
from velociraptor.utils.context_manager import ContextManager
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)


async def rawr(prompt: str, continue_conversation: bool = False) -> str:
    """
    Generate a response using Gemini LLM with MCP tool support.
    
    Args:
        prompt: The user prompt to send to the LLM
        continue_conversation: If True, continue existing session; if False, create new session
        
    Returns:
        The LLM response string
        
    Raises:
        Exception: If there's an error during processing
    """
    try:
        # Initialize context manager
        context_manager = ContextManager()
        
        # Handle session management
        if not continue_conversation:
            # Create new session
            context_manager.create_new_session()
            
            # Load and publish system prompt for new conversation
            system_prompt_path = Path(__file__).parent.parent / "prompts" / "mcp_client_system_prompt.md"
            
            try:
                with open(system_prompt_path, 'r', encoding='utf-8') as f:
                    system_prompt = f.read()
                
                context_manager.publish_system_prompt(system_prompt)
                logger.info("Added system prompt to conversation context")
            except FileNotFoundError:
                logger.warning(f"System prompt file not found at {system_prompt_path}")
            except Exception as e:
                logger.error(f"Error reading system prompt: {e}", exc_info=True)
        else:
            # Continuing existing conversation
            if context_manager.has_existing_context():
                logger.info(f"Continuing conversation with {context_manager.get_message_count()} existing messages")
            else:
                logger.warning("Continue flag set but no existing context found, starting new conversation")

        # Publish user prompt to context
        context_manager.publish_user_prompt(prompt)
        
        # Get the full conversation context for the LLM
        conversation_history = context_manager.get_context()
        full_prompt = conversation_history.get_formatted_prompt()

        # Use MCP-enabled Gemini client
        async with MCPGeminiClient(context_manager=context_manager) as client:
            logger.info("Processing prompt with MCP-enabled Gemini")
            response = await client.prompt(full_prompt)
            logger.info("Successfully generated response")
            
            # Publish AI response to context
            context_manager.publish_ai_response(response)
            
            return response
            
    except Exception as e:
        logger.error(f"Error in rawr function: {e}", exc_info=True)
        raise