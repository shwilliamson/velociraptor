"""Conversation data models for MCP client."""

import json
from dataclasses import dataclass, asdict
from typing import Optional, List, Dict, Any
from enum import Enum


class MessageType(Enum):
    """Types of messages in the conversation history."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


@dataclass
class MessagePart:
    """Represents a part of a message (text, image, etc.)."""
    type: str  # "text", "image", "file"
    content: str
    mime_type: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MessagePart':
        return cls(**data)


@dataclass
class ToolCall:
    """Represents a tool call within a message."""
    tool_name: str
    tool_id: str
    parameters: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolCall':
        return cls(**data)


@dataclass
class ToolResult:
    """Represents the result of a tool call."""
    tool_call_id: str
    result: Any
    error: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ToolResult':
        return cls(**data)


@dataclass
class ConversationMessage:
    """Represents a single message in the conversation."""
    type: MessageType
    parts: List[MessagePart]
    tool_calls: Optional[List[ToolCall]] = None
    tool_results: Optional[List[ToolResult]] = None
    timestamp: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        data = {
            "type": self.type.value,
            "parts": [part.to_dict() for part in self.parts],
            "timestamp": self.timestamp
        }
        if self.tool_calls:
            data["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.tool_results:
            data["tool_results"] = [tr.to_dict() for tr in self.tool_results]
        return data
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationMessage':
        parts = [MessagePart.from_dict(part) for part in data["parts"]]
        tool_calls = None
        if "tool_calls" in data and data["tool_calls"]:
            tool_calls = [ToolCall.from_dict(tc) for tc in data["tool_calls"]]
        tool_results = None
        if "tool_results" in data and data["tool_results"]:
            tool_results = [ToolResult.from_dict(tr) for tr in data["tool_results"]]
        
        return cls(
            type=MessageType(data["type"]),
            parts=parts,
            tool_calls=tool_calls,
            tool_results=tool_results,
            timestamp=data.get("timestamp")
        )


@dataclass
class ConversationHistory:
    """Represents the entire conversation history."""
    messages: List[ConversationMessage]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "messages": [msg.to_dict() for msg in self.messages]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConversationHistory':
        messages = [ConversationMessage.from_dict(msg) for msg in data["messages"]]
        return cls(messages=messages)
    
    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> 'ConversationHistory':
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls.from_dict(data)
    
    def add_message(self, message: ConversationMessage) -> None:
        """Add a message to the conversation history."""
        self.messages.append(message)
    
    def get_formatted_prompt(self) -> str:
        """Convert conversation history to a formatted prompt string."""
        prompt_parts = []
        
        for message in self.messages:
            if message.type == MessageType.SYSTEM:
                # System messages go at the beginning
                for part in message.parts:
                    if part.type == "text":
                        prompt_parts.insert(0, part.content)
            elif message.type == MessageType.USER:
                for part in message.parts:
                    if part.type == "text":
                        prompt_parts.append(f"User: {part.content}")
            elif message.type == MessageType.ASSISTANT:
                for part in message.parts:
                    if part.type == "text":
                        prompt_parts.append(f"Assistant: {part.content}")
            elif message.type == MessageType.TOOL_CALL:
                if message.tool_calls:
                    for tool_call in message.tool_calls:
                        prompt_parts.append(f"Tool Call: {tool_call.tool_name}({tool_call.parameters})")
            elif message.type == MessageType.TOOL_RESULT:
                if message.tool_results:
                    for tool_result in message.tool_results:
                        prompt_parts.append(f"Tool Result: {tool_result.result}")
        
        return "\n\n".join(prompt_parts)