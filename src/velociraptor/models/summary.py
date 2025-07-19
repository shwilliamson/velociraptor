from dataclasses import dataclass

from velociraptor.models.node import Node


@dataclass
class Summary(Node):
    summary: str