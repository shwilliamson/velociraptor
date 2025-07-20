import logging
import os
from typing import Optional

from google import genai
from google.genai.types import Part, GenerateContentConfig

from velociraptor.models.attachment import Attachment

logger = logging.getLogger(__name__)


class Gemini:
    def __init__(self):
        """Initialize Gemini LLM with API key."""
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    def prompt(self, prompt: str, attachments: Optional[list[Attachment]] = None, response_json_schema: Optional[dict] = None) -> str:
        """
        Submit a prompt with optional attachments to Gemini 2.5 Pro.
        
        Args:
            prompt: The text prompt to send
            attachments: List of Attachment objects to include
            response_json_schema: json schema for response
            
        Returns:
            The string response from the model
        """
        try:
            contents = [Part.from_text(text=prompt)]
            
            if attachments:
                for attachment in attachments:
                    try:
                        with open(attachment.file_path, 'rb') as f:
                            file_data = f.read()

                        file_part = Part.from_bytes(
                            data=file_data,
                            mime_type=attachment.mime_type
                        )
                        contents.append(file_part)
                    except Exception as e:
                        logger.error(f"Failed to read attachment {attachment.file_path}: {e}", exc_info=True)
                        raise

            config = GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=response_json_schema
            ) if response_json_schema else None

            response = self.client.models.generate_content(
                model='gemini-2.5-pro',
                contents=contents,
                config=config
            )
            
            return response.text
            
        except Exception as e:
            logger.error(f"Error generating content with Gemini: {e}", exc_info=True)
            raise

    def embed(self, text: str) -> list[float]:
        """
        Generate embeddings for the given text using Gemini's embedding model.
        
        Args:
            text: The text to embed
            
        Returns:
            A list of floats representing the embedding vector
        """
        try:
            response = self.client.models.embed_content(
                model='gemini-embedding-001',
                contents=[text]
            )
            
            return response.embedding
            
        except Exception as e:
            logger.error(f"Error generating embeddings with Gemini: {e}", exc_info=True)
            raise