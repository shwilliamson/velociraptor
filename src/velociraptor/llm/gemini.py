import os
import time
from typing import Optional, AsyncGenerator

import aiofiles
from google import genai
from google.genai.types import Part, GenerateContentConfig

from velociraptor.models.attachment import Attachment
from velociraptor.models.chunk import Chunk
from velociraptor.utils.logger import get_logger

logger = get_logger(__name__)


class Gemini:
    def __init__(self):
        """Initialize Gemini LLM with API key."""
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    async def prompt(self, prompt: str, attachments: Optional[list[Attachment]] = None, response_json_schema: Optional[dict] = None, retry_count: int = 0) -> str:
        """
        Submit a prompt with optional attachments to Gemini 2.5 Pro.
        
        Args:
            prompt: The text prompt to send
            attachments: List of Attachment objects to include
            response_json_schema: json schema for response
            retry_count: Current retry attempt (internal use)
            
        Returns:
            The string response from the model
        """
        try:
            start_time = time.time()
            logger.info(f"Begin prompt (attempt {retry_count + 1})")
            contents = [Part.from_text(text=prompt)]
            
            if attachments:
                for attachment in attachments:
                    try:
                        async with aiofiles.open(attachment.file_path, 'rb') as f:
                            file_data = await f.read()

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

            response = await self.client.aio.models.generate_content(
                model='gemini-2.5-flash',
                contents=contents,
                config=config,
                request_options={'timeout': 60}
            )

            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"End prompt ({processing_time_ms}ms)")
            return response.text
            
        except Exception as e:
            if retry_count < 2:
                logger.warning(f"Error generating content with Gemini (attempt {retry_count + 1}): {e}, retrying...", exc_info=True)
                return await self.prompt(prompt, attachments, response_json_schema, retry_count + 1)
            else:
                logger.error(f"Error generating content with Gemini after {retry_count + 1} attempts: {e}", exc_info=True)
                raise

    async def embed(self, text_chunks: list[str], retry_count: int = 0) -> AsyncGenerator[Chunk, None]:
        """
        Generate embeddings for the given text using Gemini's embedding model.
        
        Args:
            text_chunks: The text to embed
            retry_count: Current retry attempt (internal use)
            
        Yields:
            Chunk objects with text and embedding
        """
        try:
            start_time = time.time()
            logger.info(f"Begin embedding {len(text_chunks)} chunks (attempt {retry_count + 1})")
            chunk_sequence = 0
            batch_size = 20
            
            for i in range(0, len(text_chunks), batch_size):
                batch = text_chunks[i:i + batch_size]
                
                response = await self.client.aio.models.embed_content(
                    model='gemini-embedding-001',
                    contents=batch,
                    request_options={'timeout': 60}
                )

                for text, embedding in zip(batch, response.embeddings):
                    vector = embedding.values if embedding.values else []
                    yield Chunk(text=text, embedding=vector, sequence=chunk_sequence)
                    chunk_sequence += 1

            processing_time_ms = int((time.time() - start_time) * 1000)
            logger.info(f"End embedding {len(text_chunks)} chunks ({processing_time_ms}ms)")
        except Exception as e:
            if retry_count < 2:
                logger.warning(f"Error generating embeddings with Gemini (attempt {retry_count + 1}): {e}, retrying...", exc_info=True)
                async for chunk in self.embed(text_chunks, retry_count + 1):
                    yield chunk
            else:
                logger.error(f"Error generating embeddings with Gemini after {retry_count + 1} attempts: {e}", exc_info=True)
                raise