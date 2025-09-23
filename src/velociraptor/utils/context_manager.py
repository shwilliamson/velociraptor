from pathlib import Path
from typing import Optional, Dict, Any, List
from datetime import datetime
import json

from velociraptor.models.conversation import (
    ConversationHistory,
    ConversationMessage,
    MessagePart,
    MessageType,
    ToolCall,
    ToolResult
)
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)


class ContextManager:
    """Centralized manager for conversation context and .context.json file operations."""
    
    def __init__(self, context_file_path: Optional[Path] = None):
        """
        Initialize the ContextManager.
        
        Args:
            context_file_path: Path to the context file. Defaults to .context.json in current directory.
        """
        self.context_file_path = context_file_path or Path(".context.json")
        self._conversation_history: Optional[ConversationHistory] = None
        
    def create_new_session(self) -> None:
        """Create a new conversation session, clearing any existing context."""
        logger.info("Creating new conversation session")
        self._conversation_history = ConversationHistory(messages=[])
        self._save_context()
        
    def get_context(self) -> ConversationHistory:
        """
        Get the current conversation context.
        
        Returns:
            Current conversation history, loading from file if not already loaded.
        """
        if self._conversation_history is None:
            self._load_context()
        return self._conversation_history or ConversationHistory(messages=[])
    
    def publish_system_prompt(self, system_prompt: str) -> None:
        """
        Publish a system prompt to the conversation context.
        
        Args:
            system_prompt: The system prompt content
        """
        logger.debug("Publishing system prompt to context")
        message = ConversationMessage(
            type=MessageType.SYSTEM,
            parts=[MessagePart(type="text", content=system_prompt)],
            timestamp=datetime.now().isoformat()
        )
        self._add_message(message)
        
    def publish_user_prompt(self, user_prompt: str) -> None:
        """
        Publish a user prompt to the conversation context.
        
        Args:
            user_prompt: The user prompt content
        """
        logger.debug("Publishing user prompt to context")
        message = ConversationMessage(
            type=MessageType.USER,
            parts=[MessagePart(type="text", content=user_prompt)],
            timestamp=datetime.now().isoformat()
        )
        self._add_message(message)
        
    def publish_ai_response(self, ai_response: str) -> None:
        """
        Publish an AI assistant response to the conversation context.
        
        Args:
            ai_response: The AI response content
        """
        logger.debug("Publishing AI response to context")
        message = ConversationMessage(
            type=MessageType.ASSISTANT,
            parts=[MessagePart(type="text", content=ai_response)],
            timestamp=datetime.now().isoformat()
        )
        self._add_message(message)
        
    def publish_tool_calls(self, tool_calls: List[ToolCall]) -> None:
        """
        Publish tool calls to the conversation context.
        
        Args:
            tool_calls: List of tool calls made
        """
        logger.debug(f"Publishing {len(tool_calls)} tool calls to context")
        message = ConversationMessage(
            type=MessageType.TOOL_CALL,
            parts=[MessagePart(type="text", content=f"Executed {len(tool_calls)} tool calls")],
            tool_calls=tool_calls,
            timestamp=datetime.now().isoformat()
        )
        self._add_message(message)
        
    def publish_tool_results(self, tool_results: List[ToolResult]) -> None:
        """
        Publish tool results to the conversation context.
        
        Args:
            tool_results: List of tool results received
        """
        logger.debug(f"Publishing {len(tool_results)} tool results to context")
        message = ConversationMessage(
            type=MessageType.TOOL_RESULT,
            parts=[MessagePart(type="text", content=f"Tool results for {len(tool_results)} calls")],
            tool_results=tool_results,
            timestamp=datetime.now().isoformat()
        )
        self._add_message(message)
        
    def publish_tool_request(self, tool_name: str, tool_arguments: Dict[str, Any]) -> str:
        """
        Publish a tool request and return a unique call ID for tracking.
        
        Args:
            tool_name: Name of the tool being called
            tool_arguments: Arguments passed to the tool
            
        Returns:
            Unique tool call ID for tracking the result
        """
        call_id = f"call_{tool_name}_{int(datetime.now().timestamp() * 1000)}"
        logger.debug(f"Publishing tool request: {tool_name} with call ID: {call_id}")
        
        tool_call = ToolCall(
            tool_name=tool_name,
            tool_id=call_id,
            parameters=tool_arguments
        )
        self.publish_tool_calls([tool_call])
        return call_id
        
    def publish_tool_result(self, call_id: str, result: Any, error: Optional[str] = None) -> None:
        """
        Publish a tool result for a specific call ID.
        
        Args:
            call_id: The tool call ID returned from publish_tool_request
            result: The tool result data
            error: Error message if the tool call failed
        """
        logger.debug(f"Publishing tool result for call ID: {call_id}")
        tool_result = ToolResult(
            tool_call_id=call_id,
            result=result,
            error=error
        )
        self.publish_tool_results([tool_result])
        
    def has_existing_context(self) -> bool:
        """
        Check if there is existing context available.
        
        Returns:
            True if context file exists and has content, False otherwise
        """
        return self.context_file_path.exists() and self.context_file_path.stat().st_size > 0
        
    def get_message_count(self) -> int:
        """
        Get the number of messages in the current context.
        
        Returns:
            Number of messages in conversation history
        """
        context = self.get_context()
        return len(context.messages)
        
    def _add_message(self, message: ConversationMessage) -> None:
        """
        Add a message to the conversation history and save to file.
        
        Args:
            message: The conversation message to add
        """
        if self._conversation_history is None:
            self._load_context()
        if self._conversation_history is None:
            self._conversation_history = ConversationHistory(messages=[])
            
        self._conversation_history.add_message(message)
        self._save_context()
        
    def _load_context(self) -> None:
        """Load conversation context from the context file."""
        try:
            if self.context_file_path.exists():
                with open(self.context_file_path, 'r', encoding='utf-8') as f:
                    json_content = f.read()
                self._conversation_history = ConversationHistory.from_json(json_content)
                logger.info(f"Loaded conversation history with {len(self._conversation_history.messages)} messages")
            else:
                logger.info("No existing context file found, starting with empty history")
                self._conversation_history = ConversationHistory(messages=[])
        except Exception as e:
            logger.error(f"Error loading conversation context: {e}", exc_info=True)
            self._conversation_history = ConversationHistory(messages=[])
            
    def _save_context(self) -> None:
        """Save conversation context to the context file."""
        if self._conversation_history is None:
            return
            
        try:
            with open(self.context_file_path, 'w', encoding='utf-8') as f:
                f.write(self._conversation_history.to_json())
            logger.debug(f"Context saved to {self.context_file_path} with {len(self._conversation_history.messages)} messages")
        except Exception as e:
            logger.error(f"Error saving conversation context: {e}", exc_info=True)