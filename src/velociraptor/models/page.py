from dataclasses import dataclass

from velociraptor.models.node import Node


@dataclass
class Page(Node):
    file_name: str
    file_path: str
    mime_type: str