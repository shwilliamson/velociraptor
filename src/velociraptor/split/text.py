from langchain_text_splitters import RecursiveCharacterTextSplitter
from velociraptor.llm.gemini import Gemini
from velociraptor.models.chunk import Chunk


llm = Gemini()


def chunk_text_for_embedding(text: str, chunk_size: int = 2000, chunk_overlap: int = 200) -> list[Chunk]:
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
        is_separator_regex=False,
    )
    
    text_chunks = text_splitter.split_text(text)
    vectors = llm.embed(text_chunks)
    chunks: list[Chunk] = []
    for chunk_text in text_chunks:

        chunks.append(Chunk(text=chunk_text, embedding=vector))
    
    return chunks