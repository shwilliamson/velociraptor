from dataclasses import dataclass, field
import uuid


@dataclass
class Node:
    """Base class for all Neo4j node models."""
    uuid: str = field(default_factory=lambda: str(uuid.uuid4()), init=False)
    
    @property
    def label(self) -> str:
        """Returns the class name to be used as the Neo4j node label."""
        return self.__class__.__name__