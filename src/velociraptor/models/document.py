from dataclasses import dataclass, field

from velociraptor.models.node import Node


@dataclass
class Document(Node):
    summary: str
    file_name: str
    file_path: str
    mime_type: str
    document_uuid: str = field(default_factory=lambda: "")
    
    def __post_init__(self):
        if not self.document_uuid:
            self.document_uuid = self.uuid