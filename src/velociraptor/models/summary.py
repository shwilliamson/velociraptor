from dataclasses import dataclass

from velociraptor.models.node import DocumentTreeNode


@dataclass
class Summary(DocumentTreeNode):
    summary: str