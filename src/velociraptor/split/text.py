from typing import Generator

from langchain_text_splitters import RecursiveCharacterTextSplitter
from velociraptor.llm.gemini import Gemini
from velociraptor.models.chunk import Chunk


llm = Gemini()


def chunk_and_embed(
        text: str,
        chunk_size: int = 2000,
        chunk_overlap: int = 200
) -> Generator[Chunk, None, None]:
    if not text:
        return

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )
    
    text_chunks = text_splitter.split_text(text)
    for chunk in llm.embed(text_chunks):
        yield chunk