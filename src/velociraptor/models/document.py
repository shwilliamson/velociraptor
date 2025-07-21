from dataclasses import dataclass, field
from typing import Dict, Any

from velociraptor.models.node import DocumentTreeNode


@dataclass
class Document(DocumentTreeNode):
    text: str
    file_name: str
    file_path: str
    mime_type: str
    document_uuid: str = field(init=False)
    
    def __post_init__(self):
        self.document_uuid = self.uuid
    
    @classmethod
    def from_neo4j(cls, props: Dict[str, Any]) -> 'Document':
        """Factory method to create Document from Neo4j properties."""
        doc = cls(
            text=props["text"],
            height=props["height"],
            position=props["position"],
            file_path=props["file_path"],
            file_name=props["file_name"],
            mime_type=props["mime_type"]
        )
        doc.uuid = props["uuid"]
        return doc
