"""Neo4j triple store wrapper.

Uses Option B from the design doc: properties for literal values,
relationships for references between nodes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from neo4j import AsyncDriver, AsyncGraphDatabase


@dataclass
class StoreConfig:
    uri: str = "bolt://localhost:7687"
    username: str = "neo4j"
    password: str = "memory-system"


class TripleStore:
    """Async Neo4j wrapper for the memory graph."""

    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    @classmethod
    async def connect(cls, config: StoreConfig | None = None) -> "TripleStore":
        config = config or StoreConfig()
        driver = AsyncGraphDatabase.driver(
            config.uri, auth=(config.username, config.password)
        )
        await driver.verify_connectivity()
        return cls(driver)

    async def close(self) -> None:
        await self._driver.close()

    # -- writes --

    async def create_node(self, node_id: str, properties: dict[str, Any]) -> None:
        """Create a node with the given id and properties."""
        props = {**properties, "id": node_id}
        async with self._driver.session() as session:
            await session.run(
                "CREATE (n:Node $props)",
                props=props,
            )

    async def create_relationship(
        self,
        from_id: str,
        rel_type: str,
        to_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        """Create a typed relationship between two existing nodes."""
        query = (
            "MATCH (a:Node {id: $from_id}), (b:Node {id: $to_id}) "
            f"CREATE (a)-[r:{rel_type}]->(b) "
        )
        if properties:
            query = (
                "MATCH (a:Node {id: $from_id}), (b:Node {id: $to_id}) "
                f"CREATE (a)-[r:{rel_type} $props]->(b) "
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
        """Fetch a node by id, returning its properties."""
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n:Node {id: $id}) RETURN n",
                id=node_id,
            )
            record = await result.single()
            if record is None:
                return None
            return dict(record["n"])

    async def query_by_type(self, node_type: str) -> list[dict[str, Any]]:
        """Get all nodes of a given type."""
        async with self._driver.session() as session:
            result = await session.run(
                "MATCH (n:Node {type: $type}) RETURN n ORDER BY n.timestamp DESC",
                type=node_type,
            )
            return [dict(record["n"]) async for record in result]

    async def get_related(
        self, node_id: str, rel_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get nodes related to the given node, optionally filtered by relationship type."""
        if rel_type:
            query = (
                f"MATCH (n:Node {{id: $id}})-[:{rel_type}]->(target:Node) "
                "RETURN target"
            )
        else:
            query = (
                "MATCH (n:Node {id: $id})-[r]->(target:Node) "
                "RETURN target, type(r) AS rel_type"
            )
        async with self._driver.session() as session:
            result = await session.run(query, id=node_id)
            return [dict(record["target"]) async for record in result]

    async def find_claims_about(self, entity_id: str) -> list[dict[str, Any]]:
        """Get the current resolved state for an entity.

        Returns claims/resolutions that haven't been superseded,
        ordered by confidence (desc) then timestamp (desc).
        """
        query = """
            MATCH (c:Node)-[:SUBJECT]->(e:Node {id: $entity_id})
            WHERE c.type IN ['Claim', 'Resolution']
            AND NOT EXISTS {
                MATCH (newer:Node)-[:SUPERSEDES]->(c)
            }
            RETURN c
            ORDER BY c.confidence DESC, c.timestamp DESC
        """
        async with self._driver.session() as session:
            result = await session.run(query, entity_id=entity_id)
            return [dict(record["c"]) async for record in result]

    async def find_unresolved_contradictions(
        self,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Find pairs of claims that contradict each other and haven't been resolved."""
        query = """
            MATCH (c1:Node)-[:CONTRADICTS]->(c2:Node)
            WHERE NOT EXISTS {
                MATCH (r:Node {type: 'Resolution'})-[:SUPERSEDES]->(c1)
            }
            AND NOT EXISTS {
                MATCH (r:Node {type: 'Resolution'})-[:SUPERSEDES]->(c2)
            }
            RETURN c1, c2
        """
        async with self._driver.session() as session:
            result = await session.run(query)
            return [
                (dict(record["c1"]), dict(record["c2"]))
                async for record in result
            ]

    async def find_recent_observations(
        self, limit: int = 20
    ) -> list[dict[str, Any]]:
        """Get recent observations, newest first."""
        query = """
            MATCH (n:Node {type: 'Observation'})
            RETURN n
            ORDER BY n.timestamp DESC
            LIMIT $limit
        """
        async with self._driver.session() as session:
            result = await session.run(query, limit=limit)
            return [dict(record["n"]) async for record in result]

    async def find_recent_claims(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get recent claims, newest first."""
        query = """
            MATCH (n:Node {type: 'Claim'})
            RETURN n
            ORDER BY n.timestamp DESC
            LIMIT $limit
        """
        async with self._driver.session() as session:
            result = await session.run(query, limit=limit)
            return [dict(record["n"]) async for record in result]

    async def find_entity_by_name(self, name: str) -> dict[str, Any] | None:
        """Find an entity node by its name property (case-insensitive)."""
        query = """
            MATCH (n:Node {type: 'Entity'})
            WHERE toLower(n.name) = toLower($name)
            RETURN n
            LIMIT 1
        """
        async with self._driver.session() as session:
            result = await session.run(query, name=name)
            record = await result.single()
            if record is None:
                return None
            return dict(record["n"])

    async def get_or_create_entity(self, name: str, node_id: str) -> str:
        """Get an existing entity by name, or create one. Returns the entity id."""
        existing = await self.find_entity_by_name(name)
        if existing:
            return existing["id"]
        await self.create_node(node_id, {"type": "Entity", "name": name})
        return node_id

    async def get_all_relationships(
        self, limit: int = 500
    ) -> list[dict[str, Any]]:
        """Get all relationships for graph visualization."""
        query = """
            MATCH (a:Node)-[r]->(b:Node)
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
