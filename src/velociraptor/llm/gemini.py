import logging
import os
import time
from typing import Optional, Generator

from google import genai
from google.genai.types import Part, GenerateContentConfig

from velociraptor.models.attachment import Attachment
from velociraptor.models.chunk import Chunk

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
            start_time = time.time()
            logger.info(f"Begin prompt")
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
                model='gemini-2.5-flash',
                contents=contents,
                config=config
            )

            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"End prompt ({processing_time_ms}ms)")
            return response.text
            
        except Exception as e:
            logger.error(f"Error generating content with Gemini: {e}", exc_info=True)
            raise

    def embed(self, text_chunks: list[str]) -> Generator[Chunk, None, None]:
        """
        Generate embeddings for the given text using Gemini's embedding model.
        
        Args:
            text_chunks: The text to embed
            
        Yields:
            Chunk objects with text and embedding
        """
        try:
            start_time = time.time()
            logger.info(f"Begin embedding {len(text_chunks)} chunks")
            chunk_sequence = 0
            batch_size = 20
            
            for i in range(0, len(text_chunks), batch_size):
                batch = text_chunks[i:i + batch_size]
                
                response = self.client.models.embed_content(
                    model='gemini-embedding-001',
                    contents=batch
                )

                for text, embedding in zip(batch, response.embeddings):
                    vector = embedding.values if embedding.values else []
                    yield Chunk(text=text, embedding=vector, sequence=chunk_sequence)
                    chunk_sequence += 1

            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"End embedding {len(text_chunks)} chunks ({processing_time_ms}ms)")
        except Exception as e:
            logger.error(f"Error generating embeddings with Gemini: {e}", exc_info=True)
            raise