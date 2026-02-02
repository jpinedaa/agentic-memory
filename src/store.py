"""Neo4j knowledge graph store.

Uses proper Neo4j labels (:Concept, :Statement, :Observation, :Source)
instead of a generic :Node label with type property. All knowledge is
stored as reified Statements linking Concepts, with full provenance.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase


@dataclass
class StoreConfig:
    """Neo4j connection configuration."""
    uri: str = field(default_factory=lambda: os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    username: str = field(default_factory=lambda: os.environ.get("NEO4J_USERNAME", "neo4j"))
    password: str = field(default_factory=lambda: os.environ.get("NEO4J_PASSWORD", "memory-system"))


class TripleStore:
    """Async Neo4j wrapper for the knowledge graph."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    @classmethod
    async def connect(cls, config: StoreConfig | None = None) -> "TripleStore":
        """Connect to Neo4j and return a TripleStore instance."""
        config = config or StoreConfig()
        driver = AsyncGraphDatabase.driver(
            config.uri, auth=(config.username, config.password)
        )
        await driver.verify_connectivity()
        store = cls(driver)
        await store.ensure_indexes()
        return store

    async def close(self) -> None:
        """Close the Neo4j driver connection."""
        await self._driver.close()

    async def ensure_indexes(self) -> None:
        """Create indexes and constraints for the knowledge graph schema."""
        statements = [
            "CREATE CONSTRAINT concept_id IF NOT EXISTS FOR (c:Concept) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT statement_id IF NOT EXISTS FOR (s:Statement) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT observation_id IF NOT EXISTS FOR (o:Observation) REQUIRE o.id IS UNIQUE",
            "CREATE CONSTRAINT source_id IF NOT EXISTS FOR (s:Source) REQUIRE s.id IS UNIQUE",
            "CREATE INDEX concept_name IF NOT EXISTS FOR (c:Concept) ON (c.name)",
            "CREATE INDEX statement_predicate IF NOT EXISTS FOR (s:Statement) ON (s.predicate)",
            "CREATE INDEX statement_created IF NOT EXISTS FOR (s:Statement) ON (s.created_at)",
            "CREATE INDEX observation_created IF NOT EXISTS FOR (o:Observation) ON (o.created_at)",
        ]
        async with self._driver.session() as session:
            for stmt in statements:
                await session.run(stmt)

    # -- writes --

    async def create_concept(
        self,
        node_id: str,
        name: str,
        kind: str = "",
        aliases: list[str] | None = None,
    ) -> None:
        """Create a Concept node."""
        async with self._driver.session() as session:
            await session.run(
                "CREATE (c:Concept {id: $id, name: $name, kind: $kind, aliases: $aliases, created_at: datetime()})",
                id=node_id,
                name=name,
                kind=kind,
                aliases=aliases or [],
            )

    async def get_or_create_concept(
        self, name: str, node_id: str, kind: str = ""
    ) -> str:
        """Get an existing concept by name (case-insensitive), or create one. Returns the concept id."""
        existing = await self.find_concept_by_name(name)
        if existing:
            return existing["id"]
        await self.create_concept(node_id, name, kind=kind)
        return node_id

    async def create_statement(
        self,
        node_id: str,
        predicate: str,
        confidence: float,
        negated: bool = False,
    ) -> None:
        """Create a Statement node (reified triple)."""
        async with self._driver.session() as session:
            await session.run(
                "CREATE (s:Statement {id: $id, predicate: $predicate, confidence: $confidence, negated: $negated, created_at: datetime()})",
                id=node_id,
                predicate=predicate,
                confidence=confidence,
                negated=negated,
            )

    async def create_observation(
        self,
        node_id: str,
        raw_content: str,
        topics: list[str] | None = None,
    ) -> None:
        """Create an Observation node."""
        async with self._driver.session() as session:
            await session.run(
                "CREATE (o:Observation {id: $id, raw_content: $raw_content, topics: $topics, created_at: datetime()})",
                id=node_id,
                raw_content=raw_content,
                topics=topics or [],
            )

    async def get_or_create_source(self, name: str, kind: str = "agent") -> str:
        """Get an existing source by name, or create one. Returns the source id."""
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (s:Source {name: $name}) RETURN s.id AS id LIMIT 1",
                name=name,
            )
            record = await result.single()
            if record:
                return record["id"]

            import uuid
            source_id = str(uuid.uuid4())
            await session.run(
                "CREATE (s:Source {id: $id, name: $name, kind: $kind, created_at: datetime()})",
                id=source_id,
                name=name,
                kind=kind,
            )
            return source_id

    async def create_relationship(
        self,
        from_id: str,
        rel_type: str,
        to_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a typed relationship between two existing nodes (any label)."""
        if properties:
            query = (
                "MATCH (a {id: $from_id}), (b {id: $to_id}) "
                f"CREATE (a)-[r:{rel_type} $props]->(b)"
            )
        else:
            query = (
                "MATCH (a {id: $from_id}), (b {id: $to_id}) "
                f"CREATE (a)-[r:{rel_type}]->(b)"
            )
        async with self._driver.session() as session:
            await session.run(
                query,
                from_id=from_id,
                to_id=to_id,
                props=properties or {},
            )

    # -- reads --

    async def get_node(self, node_id: str) -> dict[str, Any] | None:
        """Fetch any node by id, returning its properties and labels."""
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n {id: $id}) RETURN n, labels(n) AS labels",
                id=node_id,
            )
            record = await result.single()
            if record is None:
                return None
            props = dict(record["n"])
            props["_labels"] = record["labels"]
            return props

    async def find_concept_by_name(self, name: str) -> dict[str, Any] | None:
        """Find a concept by name (case-insensitive) or alias."""
        query = """
            MATCH (c:Concept)
            WHERE toLower(c.name) = toLower($name)
               OR any(a IN c.aliases WHERE toLower(a) = toLower($name))
            RETURN c
            LIMIT 1
        """
        async with self._driver.session() as session:
            result = await session.run(query, name=name)
            record = await result.single()
            if record is None:
                return None
            return dict(record["c"])

    async def find_statements_about(self, concept_id: str) -> list[dict[str, Any]]:
        """Get current statements about a concept (as subject or object, excluding superseded)."""
        query = """
            MATCH (s:Statement)-[:ABOUT_SUBJECT|ABOUT_OBJECT]->(c:Concept {id: $concept_id})
            WHERE NOT EXISTS {
                MATCH (:Statement)-[:SUPERSEDES]->(s)
            }
            OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
            OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
            RETURN s {.*, subject_name: subj.name, object_name: obj.name}
            ORDER BY s.confidence DESC, s.created_at DESC
        """
        async with self._driver.session() as session:
            result = await session.run(query, concept_id=concept_id)
            return [dict(record["s"]) async for record in result]

    async def find_unresolved_contradictions(
        self,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Find pairs of statements that contradict each other and haven't been resolved."""
        query = """
            MATCH (s1:Statement)-[:CONTRADICTS]->(s2:Statement)
            WHERE NOT EXISTS {
                MATCH (:Statement)-[:SUPERSEDES]->(s1)
            }
            AND NOT EXISTS {
                MATCH (:Statement)-[:SUPERSEDES]->(s2)
            }
            OPTIONAL MATCH (s1)-[:ABOUT_SUBJECT]->(subj1:Concept)
            OPTIONAL MATCH (s1)-[:ABOUT_OBJECT]->(obj1:Concept)
            OPTIONAL MATCH (s2)-[:ABOUT_SUBJECT]->(subj2:Concept)
            OPTIONAL MATCH (s2)-[:ABOUT_OBJECT]->(obj2:Concept)
            RETURN s1 {.*, subject_name: subj1.name, object_name: obj1.name},
                   s2 {.*, subject_name: subj2.name, object_name: obj2.name}
        """
        async with self._driver.session() as session:
            result = await session.run(query)
            return [
                (dict(record["s1"]), dict(record["s2"]))
                async for record in result
            ]

    async def find_recent_observations(
        self, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get recent observations, newest first."""
        query = """
            MATCH (o:Observation)
            RETURN o
            ORDER BY o.created_at DESC
            LIMIT $limit
        """
        async with self._driver.session() as session:
            result = await session.run(query, limit=limit)
            return [dict(record["o"]) async for record in result]

    async def find_recent_statements(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent statements with their subject and object names, newest first."""
        query = """
            MATCH (s:Statement)
            OPTIONAL MATCH (s)-[:ABOUT_SUBJECT]->(subj:Concept)
            OPTIONAL MATCH (s)-[:ABOUT_OBJECT]->(obj:Concept)
            OPTIONAL MATCH (s)-[:ASSERTED_BY]->(src:Source)
            RETURN s {.*, subject_name: subj.name, object_name: obj.name, source: src.name}
            ORDER BY s.created_at DESC
            LIMIT $limit
        """
        async with self._driver.session() as session:
            result = await session.run(query, limit=limit)
            return [dict(record["s"]) async for record in result]

    async def get_all_concepts(self) -> list[dict[str, Any]]:
        """Get all concept nodes."""
        query = """
            MATCH (c:Concept)
            RETURN c
            ORDER BY c.name
        """
        async with self._driver.session() as session:
            result = await session.run(query)
            return [dict(record["c"]) async for record in result]

    async def get_all_relationships(
        self, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Get all relationships for graph visualization."""
        query = """
            MATCH (a)-[r]->(b)
            RETURN a.id AS source, b.id AS target, type(r) AS type
            LIMIT $limit
        """
        async with self._driver.session() as session:
            result = await session.run(query, limit=limit)
            return [dict(record) async for record in result]

    async def raw_query(
        self, cypher: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute raw Cypher and return results as list of dicts."""
        async with self._driver.session() as session:
            result = await session.run(cypher, **(params or {}))
            return [dict(record) async for record in result]

    async def clear_all(self) -> None:
        """Delete all nodes and relationships. Use for testing only."""
        async with self._driver.session() as session:
            await session.run("MATCH (n) DETACH DELETE n")
