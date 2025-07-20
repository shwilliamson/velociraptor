from velociraptor.llm.gemini import Gemini
from velociraptor.models.chunk import Chunk


llm = Gemini()


def chunk_text_for_embedding(text: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    for part in text:
        vector = llm.embed(part)
        chunks.append(Chunk(text=part, embedding=vector))
    return chunks