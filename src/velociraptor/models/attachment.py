from dataclasses import dataclass


@dataclass
class Attachment:
    file_path: str
    mime_type: str