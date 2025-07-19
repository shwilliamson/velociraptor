import uuid
from typing import Any, Dict, Iterator, LiteralString, Optional, TypeVar

from neo4j import GraphDatabase


class Neo4jDb:
    _driver = None

    @property
    def driver(self):
        uri = "neo4j://localhost:7687"
        username = "neo4j"
        password = "neo4j_password"
        if self._driver is None:
            if not all([uri, username, password]):
                raise ValueError("Neo4j connection details not found in environment variables")
            self._driver = GraphDatabase.driver(uri, auth=(username, password))
        return self._driver