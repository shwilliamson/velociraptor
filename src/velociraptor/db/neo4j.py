from neo4j import AsyncGraphDatabase
from typing import TypeVar, Optional
from dataclasses import fields

from velociraptor.models.chunk import Chunk
from velociraptor.models.document import Document
from velociraptor.models.node import Node
from velociraptor.models.edge import EdgeType
from velociraptor.models.page import Page
from velociraptor.models.summary import Summary
from velociraptor.split.text import chunk_and_embed
from velociraptor.utils.logger import get_logger

T = TypeVar('T', bound=Node)
logger = get_logger(__name__)


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
            self._driver = AsyncGraphDatabase.driver(uri, auth=(username, password))
        return self._driver

    async def save_node(self, node: T) -> str:
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
        
        # Create Cypher query to upsert the node with both specific and searchable labels
        label = node.label
        cypher_query = f"MERGE (n:{label}:Searchable {{uuid: $props.uuid}}) SET n = $props RETURN n.uuid as uuid"
        
        async with self.driver.session() as session:
            result = await session.run(cypher_query, props=properties)
            record = await result.single()
            return record["uuid"]

    async def create_edge(self, from_node: Node, to_node: Node, edge_type: EdgeType) -> None:
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
        
        async with self.driver.session() as session:
            await session.run(cypher_query, from_uuid=from_node.uuid, to_uuid=to_node.uuid)

    async def link(self, previous_node: Node, next_node: Node) -> None:
        await self.create_edge(previous_node, next_node, EdgeType.NEXT)
        await self.create_edge(next_node, previous_node, EdgeType.PREVIOUS)

    async def save_chunk(self, chunk: Chunk, parent: Node):
        await self.save_node(chunk)
        await self.create_edge(chunk, parent, EdgeType.PART_OF)

    async def save_page(self, page: Page, doc: Document, prior_page: Optional[Page]):
        await self.save_node(page)
        await self.create_edge(doc, page, EdgeType.CONTAINS)
        await self.create_edge(page, doc, EdgeType.PART_OF)
        async for c in chunk_and_embed(page.text):
            await self.save_chunk(c, page)
        if prior_page:
            await self.link(prior_page, page)

    async def save_page_summary(self, summary: Summary, page: Page, prior_summary: Optional[Summary]):
        await self.save_node(summary)
        async for c in chunk_and_embed(summary.text):
            await self.save_chunk(c, summary)
        await self.create_edge(summary, page, EdgeType.SUMMARIZES)
        if prior_summary:
            await self.link(prior_summary, summary)

    async def save_summary(self, summary: Summary, prior_summary: Optional[Summary], child_summaries: list[Summary]):
        await self.save_node(summary)
        async for c in chunk_and_embed(summary.text):
            await self.save_chunk(c, summary)
        if prior_summary:
            await self.link(prior_summary, summary)
        for child in child_summaries:
            await self.create_edge(summary, child, EdgeType.SUMMARIZES)

    async def save_document(self, doc: Document, summaries: list[Summary] = []):
        await self.save_node(doc)
        async for c in chunk_and_embed(doc.text):
            await self.save_chunk(c, doc)
        for s in summaries:
            await self.create_edge(doc, s, EdgeType.SUMMARIZES)

    async def create_indexes(self):
        """Create full text and vector indexes for efficient querying."""
        logger.info("Creating indexes")
        index_queries = [
            # Single fulltext index for all searchable content
            "CREATE FULLTEXT INDEX all_text_content IF NOT EXISTS FOR (s:Searchable) ON EACH [s.text]",
            
            # Vector index on Chunk.embedding
            "CREATE VECTOR INDEX chunk_embedding_vector IF NOT EXISTS FOR (c:Chunk) ON (c.embedding) "
            "OPTIONS {indexConfig: {`vector.dimensions`: 3072, `vector.similarity_function`: 'cosine'}}"
        ]
        
        async with self.driver.session() as session:
            for query in index_queries:
                await session.run(query)
        logger.info("Finished creating indexes")