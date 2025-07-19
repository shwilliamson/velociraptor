from enum import Enum


class EdgeType(Enum):
    """Enum defining types of edges in the graph."""
    NEXT = "NEXT"
    PREVIOUS = "PREVIOUS"
    SUMMARIZES = "SUMMARIZES"
    CONTAINS = "CONTAINS"