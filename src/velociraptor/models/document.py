from dataclasses import dataclass, field

from velociraptor.models.node import Node


@dataclass
class Document(Node):
    summary: str
    file_name: str
    file_path: str
    mime_type: str
    document_uuid: str = field(init=False)
    
    def __post_init__(self):
        self.document_uuid = self.uuid
