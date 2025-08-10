from typing import Optional, Dict, List, Any
import time
import os
import json
import aiofiles
import base64

from velociraptor.models.attachment import Attachment
from velociraptor.utils.logger import get_logger


logger = get_logger(__name__)

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    anthropic = None  # type: ignore
    ANTHROPIC_AVAILABLE = False
    logger.warning("anthropic SDK not available. Install with: pip install 'anthropic[bedrock]'")


class AnthropicClient:
    """Anthropic client supporting both AWS Bedrock and direct Anthropic API."""

    def __init__(self, aws_region: str = "us-east-1", use_bedrock: Optional[bool] = None):
        if not ANTHROPIC_AVAILABLE:
            raise ImportError("anthropic SDK is required. Install with: pip install 'anthropic[bedrock]'")

        self.aws_region = aws_region

        # Determine which endpoint to use
        if use_bedrock is None:
            # Check environment variable, default to Bedrock if not specified
            use_bedrock_env = os.getenv('ANTHROPIC_USE_BEDROCK', 'true').lower()
            self.use_bedrock = use_bedrock_env in ('true', '1', 'yes')
        else:
            self.use_bedrock = use_bedrock

        self.client = None
        self._initialize_client()

    def _initialize_client(self) -> None:
        """Initialize Anthropic client (either Bedrock or direct API)."""
        if self.use_bedrock:
            # Use Anthropic's built-in Bedrock client
            self.client = anthropic.AsyncAnthropicBedrock(
                aws_region=self.aws_region
            )
            logger.info(f"Initialized Anthropic Bedrock client for region {self.aws_region}")
        else:
            # Use direct Anthropic API
            api_key = os.getenv('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable is required for direct Anthropic API access")

            self.client = anthropic.AsyncAnthropic(
                api_key=api_key
            )
            logger.info("Initialized direct Anthropic API client")

    async def prompt(
            self,
            prompt: str,
            attachments: Optional[List[Attachment]] = None,
            response_json_schema: Optional[Dict] = None,
            tools: Optional[List[Dict]] = None,
            model: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Submit a prompt to Anthropic Claude.

        Args:
            prompt: The text prompt to send
            attachments: List of Attachment objects to include
            response_json_schema: JSON schema for response (not directly supported)
            tools: List of tool definitions for function calling
            model: Model to use

        Returns:
            Dict containing response and metadata
        """
        try:
            start_time = time.time()
            logger.info(f"Begin Anthropic prompt")

            # Build messages
            messages = [{"role": "user", "content": []}]

            # Add text content
            messages[0]["content"].append({
                "type": "text",
                "text": prompt
            })

            # Add attachments as images if provided
            if attachments:
                for attachment in attachments:
                    try:
                        async with aiofiles.open(attachment.file_path, 'rb') as f:
                            file_data = await f.read()

                        # Only support images for now
                        if attachment.mime_type.startswith('image/'):
                            messages[0]["content"].append({
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": attachment.mime_type,
                                    "data": base64.b64encode(file_data).decode()
                                }
                            })
                    except Exception as e:
                        logger.error(f"Failed to read attachment {attachment.file_path}: {e}", exc_info=True)
                        raise

            # Build request parameters
            if model is None:
                # Use default model based on endpoint
                if self.use_bedrock:
                    model = "arn:aws:bedrock:us-east-1:384232296347:inference-profile/us.anthropic.claude-sonnet-4-20250514-v1:0"
                else:
                    model = "claude-3-5-sonnet-20241022"  # Direct API model

            request_params = {
                "model": model,
                "max_tokens": 4096,  # Add max_tokens for direct API
                "messages": messages,
            }

            if tools:
                request_params["tools"] = tools

            # Make request using unified client with streaming for extended thinking
            response_content = []
            response_model = None
            response_stop_reason = None
            response_usage = None

            async with self.client.messages.stream(**request_params) as stream:
                async for event in stream:
                    if hasattr(event, 'type'):
                        if event.type == "message_start":
                            response_model = event.message.model
                            response_usage = event.message.usage
                        elif event.type == "content_block_start":
                            # Initialize content block
                            if hasattr(event.content_block, 'type'):
                                if event.content_block.type == "text":
                                    response_content.append({"type": "text", "text": ""})
                                elif event.content_block.type == "tool_use":
                                    response_content.append({
                                        "type": "tool_use",
                                        "id": event.content_block.id,
                                        "name": event.content_block.name,
                                        "input": {}
                                    })
                        elif event.type == "content_block_delta":
                            # Handle streaming content - we'll collect it
                            if hasattr(event.delta, 'text'):
                                # Text content
                                if response_content and response_content[-1].get("type") == "text":
                                    response_content[-1]["text"] += event.delta.text
                            elif hasattr(event.delta, 'partial_json'):
                                # Tool use input (streaming JSON)
                                if response_content and response_content[-1].get("type") == "tool_use":
                                    # Accumulate the JSON input
                                    if "partial_input" not in response_content[-1]:
                                        response_content[-1]["partial_input"] = ""
                                    response_content[-1]["partial_input"] += event.delta.partial_json
                        elif event.type == "content_block_stop":
                            # Content block finished - finalize tool use input if needed
                            if response_content and response_content[-1].get("type") == "tool_use":
                                if "partial_input" in response_content[-1]:
                                    # Parse the accumulated JSON
                                    try:
                                        response_content[-1]["input"] = json.loads(
                                            response_content[-1]["partial_input"])
                                        del response_content[-1]["partial_input"]
                                    except json.JSONDecodeError as e:
                                        logger.error(f"Failed to parse tool input JSON: {e}")
                                        response_content[-1]["input"] = {}
                        elif event.type == "message_delta":
                            response_stop_reason = event.delta.stop_reason
                        elif event.type == "message_stop":
                            # Message finished
                            break

            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"End Anthropic prompt ({processing_time_ms}ms)")

            return {
                "content": response_content,
                "model": response_model,
                "stop_reason": response_stop_reason,
                "usage": response_usage.model_dump() if response_usage else None
            }

        except Exception as e:
            logger.error(f"Error with Anthropic prompt: {e}", exc_info=True)
            raise