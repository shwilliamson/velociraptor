from dotenv import load_dotenv
load_dotenv()

from pathlib import Path

from velociraptor.llm.gemini_mcp_client import MCPGeminiClient
from velociraptor.models.conversation import (
    ConversationHistory,
    ConversationMessage,
    MessagePart,
    MessageType
)
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
        from datetime import datetime
        context_file_path = Path(".context.json")
        conversation_history = ConversationHistory(messages=[])
        
        # Handle context file operations
        if continue_conversation:
            # Read existing conversation history
            try:
                if context_file_path.exists():
                    with open(context_file_path, 'r', encoding='utf-8') as f:
                        json_content = f.read()
                    conversation_history = ConversationHistory.from_json(json_content)
                    logger.info(f"Loaded conversation history with {len(conversation_history.messages)} messages")
                else:
                    logger.warning("Context file not found, starting new conversation")
            except Exception as e:
                logger.error(f"Error reading context file: {e}", exc_info=True)
                conversation_history = ConversationHistory(messages=[])
        else:
            # Load system prompt for new conversation
            system_prompt_path = Path(__file__).parent.parent / "prompts" / "mcp_client_system_prompt.md"
            
            try:
                with open(system_prompt_path, 'r', encoding='utf-8') as f:
                    system_prompt = f.read()
                
                # Add system message to conversation history
                system_message = ConversationMessage(
                    type=MessageType.SYSTEM,
                    parts=[MessagePart(type="text", content=system_prompt)],
                    timestamp=datetime.now().isoformat()
                )
                conversation_history.add_message(system_message)
                logger.info("Added system prompt to conversation history")
            except FileNotFoundError:
                logger.warning(f"System prompt file not found at {system_prompt_path}")
            except Exception as e:
                logger.error(f"Error reading system prompt: {e}", exc_info=True)

        # Add user message to conversation history
        user_message = ConversationMessage(
            type=MessageType.USER,
            parts=[MessagePart(type="text", content=prompt)],
            timestamp=datetime.now().isoformat()
        )
        conversation_history.add_message(user_message)
        
        # Generate the formatted prompt from conversation history
        full_prompt = conversation_history.get_formatted_prompt()

        # Use MCP-enabled Gemini client
        async with MCPGeminiClient() as client:
            logger.info("Processing prompt with MCP-enabled Gemini")
            response = await client.prompt(full_prompt)
            logger.info("Successfully generated response")
            
            # Add assistant response to conversation history
            assistant_message = ConversationMessage(
                type=MessageType.ASSISTANT,
                parts=[MessagePart(type="text", content=response)],
                timestamp=datetime.now().isoformat()
            )
            conversation_history.add_message(assistant_message)
            
            # Save updated conversation history to JSON file
            try:
                with open(context_file_path, 'w', encoding='utf-8') as f:
                    f.write(conversation_history.to_json())
                logger.info(f"Context saved to {context_file_path} with {len(conversation_history.messages)} messages")
            except Exception as e:
                logger.error(f"Error saving context file: {e}", exc_info=True)
            
            return response
            
    except Exception as e:
        logger.error(f"Error in rawr function: {e}", exc_info=True)
        raise