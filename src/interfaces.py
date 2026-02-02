"""Memory service interfaces.

Framework-agnostic API that any agent runtime can call.
Satisfies the MemoryAPI protocol for both in-process and distributed use.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from src.llm import LLMTranslator
from src.store import TripleStore

logger = logging.getLogger(__name__)


def _new_id() -> str:
    return str(uuid.uuid4())


class MemoryService:
    """Core memory API. Composes the triple store and LLM translator.

    All operations are async. Source identity is passed per-call so that
    a single MemoryService instance can serve multiple callers.
    """

    def __init__(self, store: TripleStore, llm: LLMTranslator) -> None:
        self.store = store
        self.llm = llm

    async def observe(self, text: str, source: str) -> str:
        """Record an observation from the external world.

        The LLM extracts concepts (with decomposition) from the text.
        Statements are NOT created here — the inference agent is
        responsible for all statement creation from observations.
        Returns the observation node ID.
        """
        obs_id = _new_id()
        extraction = await self.llm.extract_observation(text)

        # Ensure source exists
        source_id = await self.store.get_or_create_source(source, kind="user")

        # Create the observation node
        await self.store.create_observation(obs_id, raw_content=text, topics=extraction.topics)
        await self.store.create_relationship(obs_id, "RECORDED_BY", source_id)

        # Create concepts and link to observation
        for concept in extraction.concepts:
            cid = await self.store.get_or_create_concept(
                concept.name, _new_id(), kind=concept.kind
            )
            await self.store.create_relationship(obs_id, "MENTIONS", cid)

            # Decompose compound concepts
            for component in concept.components:
                comp_id = await self.store.get_or_create_concept(
                    component.name, _new_id()
                )
                await self.store.create_relationship(
                    cid, "RELATED_TO", comp_id, {"relation": component.relation}
                )

        return obs_id

    async def claim(self, text: str, source: str) -> str:
        """Assert a claim (inference, fact, or resolution).

        The LLM parses the claim into structured data. Contradiction
        detection is NOT done here — that's the validator agent's job
        via flag_contradiction(). Returns the statement node ID.
        """
        # Gather recent context for the LLM to reference
        recent_statements = await self.store.find_recent_statements(limit=10)
        recent_obs = await self.store.find_recent_observations(limit=10)
        context = [
            {**s, "node_kind": "statement"} for s in recent_statements
        ] + [
            {**o, "node_kind": "observation"} for o in recent_obs
        ]

        parsed = await self.llm.parse_claim(text, context)

        source_id = await self.store.get_or_create_source(source, kind="agent")

        stmt_id = _new_id()
        await self.store.create_statement(
            stmt_id, parsed.predicate, parsed.confidence, parsed.negated
        )

        # Link to subject and object concepts
        subj_id = await self.store.get_or_create_concept(parsed.subject, _new_id())
        obj_id = await self.store.get_or_create_concept(parsed.object, _new_id())
        await self.store.create_relationship(stmt_id, "ABOUT_SUBJECT", subj_id)
        await self.store.create_relationship(stmt_id, "ABOUT_OBJECT", obj_id)
        await self.store.create_relationship(stmt_id, "ASSERTED_BY", source_id)

        # Link basis — match descriptions to existing nodes
        for basis_desc in parsed.basis_descriptions:
            basis_node = await self._find_matching_node(basis_desc)
            if basis_node:
                await self.store.create_relationship(
                    stmt_id, "DERIVED_FROM", basis_node["id"]
                )

        # Link supersession (explicit resolution, not contradiction detection)
        if parsed.supersedes_description:
            superseded = await self._find_matching_node(
                parsed.supersedes_description
            )
            if superseded:
                await self.store.create_relationship(
                    stmt_id, "SUPERSEDES", superseded["id"]
                )

        return stmt_id

    async def flag_contradiction(
        self, stmt_id_1: str, stmt_id_2: str, reason: str = ""
    ) -> None:
        """Create a CONTRADICTS relationship between two statements directly.

        Used by the validator agent to bypass the LLM round-trip when it
        already has exact statement IDs.
        """
        props = {"reason": reason} if reason else None
        await self.store.create_relationship(
            stmt_id_1, "CONTRADICTS", stmt_id_2, props
        )
        logger.info(
            "Flagged contradiction: %s <-> %s (reason: %s)",
            stmt_id_1, stmt_id_2, reason or "none",
        )

    async def remember(self, query: str) -> str:
        """Query the knowledge graph and return a resolved natural language response."""
        # Generate and execute the graph query
        try:
            cypher = await self.llm.generate_query(query)
            results = await self.store.raw_query(cypher)
        except Exception:  # pylint: disable=broad-exception-caught  # fallback to broad search if query generation fails
            results = []

        # If the generated query returned nothing, fall back to broad search
        if not results:
            results = await self._broad_search(query)

        # Synthesize a natural language response
        serializable = []
        for record in results:
            row = {}
            for key, val in record.items():
                if hasattr(val, "items"):
                    row[key] = dict(val)
                else:
                    row[key] = val
            serializable.append(row)

        return await self.llm.synthesize_response(query, serializable)

    # pylint: disable-next=unused-argument  # `query` kept for interface consistency
    async def _broad_search(self, query: str) -> list[dict]:
        """Fallback search: get recent observations and statements."""
        obs = await self.store.find_recent_observations(limit=10)
        statements = await self.store.find_recent_statements(limit=10)
        results = []
        for o in obs:
            results.append({"node": o, "kind": "observation"})
        for s in statements:
            results.append({"node": s, "kind": "statement"})
        return results

    async def _find_matching_node(self, description: str) -> dict | None:
        """Best-effort match a textual description to an existing node."""
        description_lower = description.lower()

        # Search observations
        for obs in await self.store.find_recent_observations(limit=20):
            raw = obs.get("raw_content", "").lower()
            if raw and _text_overlap(description_lower, raw):
                return obs

        # Search statements
        for stmt in await self.store.find_recent_statements(limit=20):
            parts = [
                stmt.get("subject_name", ""),
                stmt.get("predicate", ""),
                stmt.get("object_name", ""),
            ]
            combined = " ".join(parts).lower()
            if _text_overlap(description_lower, combined):
                return stmt

        return None

    # -- Facade methods (satisfy MemoryAPI protocol) --

    async def get_recent_observations(self, limit: int = 10) -> list[dict[str, Any]]:
        """Return recent observations from the store."""
        return await self.store.find_recent_observations(limit=limit)

    async def get_recent_statements(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent statements from the store."""
        return await self.store.find_recent_statements(limit=limit)

    async def get_unresolved_contradictions(
        self,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        """Return unresolved contradiction pairs."""
        return await self.store.find_unresolved_contradictions()

    async def get_concepts(self) -> list[dict[str, Any]]:
        """Return all concept nodes."""
        return await self.store.get_all_concepts()

    async def infer(self, observation_text: str) -> str | None:
        """Use the LLM to produce an inference claim from an observation."""
        return await self.llm.infer(observation_text)

    async def clear(self) -> None:
        """Clear all data from the graph."""
        await self.store.clear_all()


def _text_overlap(a: str, b: str) -> bool:
    """Check if two strings share significant word overlap."""
    words_a = set(a.split())
    words_b = set(b.split())
    # Remove common stopwords
    stopwords = {"the", "a", "an", "is", "are", "was", "were", "that", "this", "of", "in", "to", "for", "and", "or"}
    words_a -= stopwords
    words_b -= stopwords
    if not words_a or not words_b:
        return False
    overlap = words_a & words_b
    return len(overlap) >= min(2, len(words_a))
