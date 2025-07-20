from neo4j import GraphDatabase
from typing import TypeVar
from dataclasses import fields
from velociraptor.models.node import Node
from velociraptor.models.edge import EdgeType

T = TypeVar('T', bound=Node)


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

    def save_node(self, node: T) -> str:
        """Save a Node instance to Neo4j with its label and all field properties.
        
        Args:
            node: Any instance that extends the Node base class
            
        Returns:
            str: The UUID of the saved node
        """
        # Get all dataclass fields and their values
        node_fields = fields(node)
        properties = {}
        
        for field in node_fields:
            value = getattr(node, field.name)
            # Convert value to a format suitable for Neo4j
            if value is not None:
                properties[field.name] = value
        
        # Create Cypher query to upsert the node
        label = node.label
        cypher_query = f"MERGE (n:{label} {{uuid: $props.uuid}}) SET n = $props RETURN n.uuid as uuid"
        
        with self.driver.session() as session:
            result = session.run(cypher_query, props=properties)
            return result.single()["uuid"]

    def create_edge(self, from_node: Node, to_node: Node, edge_type: EdgeType) -> None:
        """Create a directional edge between two nodes in Neo4j.
        
        Args:
            from_node: source node
            to_node: target node
            edge_type: Type of edge from EdgeType enum
        """
        cypher_query = f"""
        MATCH (from_node {{uuid: $from_uuid}})
        MATCH (to_node {{uuid: $to_uuid}})
        MERGE (from_node)-[:{edge_type.value}]->(to_node)
        """
        
        with self.driver.session() as session:
            session.run(cypher_query, from_uuid=from_node.uuid, to_uuid=to_node.uuid)

    def link(self, previous_node: Node, next_node: Node) -> None:
        self.create_edge(previous_node, next_node, EdgeType.NEXT)
        self.create_edge(next_node, previous_node, EdgeType.PREVIOUS)

    def create_indexes(self):
        pass