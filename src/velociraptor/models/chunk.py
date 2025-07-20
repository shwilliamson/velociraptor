from dataclasses import dataclass

from velociraptor.models.node import Node


@dataclass
class Chunk(Node):
    text: str
    embedding: list[float]