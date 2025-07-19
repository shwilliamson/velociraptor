from dataclasses import dataclass

from velociraptor.models.node import Node


@dataclass
class Chunk(Node):
    chunk: str
    embedding: list[float]