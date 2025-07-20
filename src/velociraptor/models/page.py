from dataclasses import dataclass

from velociraptor.models.node import DocumentTreeNode


@dataclass
class Page(DocumentTreeNode):
    file_name: str
    file_path: str
    mime_type: str
    text: str
    page_number: int = -1
    has_graphics: bool = False
    has_tabular_data: bool = False