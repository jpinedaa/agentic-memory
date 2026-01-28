"""Memory service interfaces.

Framework-agnostic API that any agent runtime can call.
Satisfies the MemoryAPI protocol for both in-process and distributed use.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.llm import LLMTranslator
from src.prompts import PromptLoader, InferenceVars
from src.store import TripleStore

logger = logging.getLogger(__name__)


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class MemoryService:
    """Core memory API. Composes the triple store and LLM translator.

    All operations are async. Source identity is passed per-call so that
    a single MemoryService instance can serve multiple callers.
    """

    def __init__(self, store: TripleStore, llm: LLMTranslator) -> None:
        self.store = store
        self.llm = llm
        self._prompt_loader = PromptLoader()

    async def observe(self, text: str, source: str) -> str:
        """Record an observation from the external world.

        The LLM extracts entities and relationships from the text.
        Returns the observation node ID.
        """
        obs_id = _new_id()
        extraction = await self.llm.extract_observation(text)

        # Create the observation node
        await self.store.create_node(obs_id, {
            "type": "Observation",
            "source": source,
            "timestamp": _now(),
            "raw_content": text,
            "topics": ",".join(extraction.topics),
        })

        # Ensure entity nodes exist and link them
        for entity_name in extraction.entities:
            entity_id = await self.store.get_or_create_entity(
                entity_name, _new_id()
            )
            await self.store.create_relationship(obs_id, "SUBJECT", entity_id)

        # Store extracted relationships as properties on the observation
        for i, ext in enumerate(extraction.extractions):
            await self.store.create_node(obs_id, {}) if False else None  # node already exists
            # Store extractions as separate triple nodes linked to the observation
            triple_id = _new_id()
            await self.store.create_node(triple_id, {
                "type": "ExtractedTriple",
                "subject_text": ext.subject,
                "predicate_text": ext.predicate,
                "object_text": ext.object,
                "timestamp": _now(),
            })
            await self.store.create_relationship(obs_id, "HAS_EXTRACTION", triple_id)

        return obs_id

    async def claim(self, text: str, source: str) -> str:
        """Assert a claim (inference, fact, contradiction, or resolution).

        The LLM parses the claim, identifies basis, confidence, and
        contradiction/supersession. Returns the claim node ID.
        """
        # Gather recent context for the LLM to reference
        recent_claims = await self.store.find_recent_claims(limit=10)
        recent_obs = await self.store.find_recent_observations(limit=10)
        context = [
            {**c, "node_kind": "claim"} for c in recent_claims
        ] + [
            {**o, "node_kind": "observation"} for o in recent_obs
        ]

        parsed = await self.llm.parse_claim(text, context)

        # Determine node type
        node_type = "Claim"
        if parsed.supersedes_description:
            node_type = "Resolution"

        claim_id = _new_id()
        await self.store.create_node(claim_id, {
            "type": node_type,
            "source": source,
            "timestamp": _now(),
            "subject_text": parsed.subject,
            "predicate_text": parsed.predicate,
            "object_text": parsed.object,
            "confidence": parsed.confidence,
        })

        # Link to entity
        entity_id = await self.store.get_or_create_entity(
            parsed.subject, _new_id()
        )
        await self.store.create_relationship(claim_id, "SUBJECT", entity_id)

        # Link basis — match descriptions to existing nodes
        for basis_desc in parsed.basis_descriptions:
            basis_node = await self._find_matching_node(basis_desc)
            if basis_node:
                await self.store.create_relationship(
                    claim_id, "BASIS", basis_node["id"]
                )

        # Link supersession
        if parsed.supersedes_description:
            superseded = await self._find_matching_node(
                parsed.supersedes_description
            )
            if superseded:
                await self.store.create_relationship(
                    claim_id, "SUPERSEDES", superseded["id"]
                )

        # Link contradiction
        if parsed.contradicts_description:
            contradicted = await self._find_matching_node(
                parsed.contradicts_description
            )
            if contradicted:
                await self.store.create_relationship(
                    claim_id, "CONTRADICTS", contradicted["id"]
                )

        return claim_id

    async def remember(self, query: str) -> str:
        """Query the knowledge graph and return a resolved natural language response.

        The LLM translates the question to a Cypher query, executes it,
        then synthesizes a response that accounts for supersession and
        contradiction resolution.
        """
        # Generate and execute the graph query
        try:
            cypher = await self.llm.generate_query(query)
            results = await self.store.raw_query(cypher)
        except Exception:
            # Fallback: gather broad context if query generation fails
            results = []

        # If the generated query returned nothing, fall back to broad search
        if not results:
            results = await self._broad_search(query)

        # Synthesize a natural language response
        # Convert neo4j node objects to plain dicts for serialization
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

    async def _broad_search(self, query: str) -> list[dict]:
        """Fallback search: get recent observations, claims, and resolutions."""
        obs = await self.store.find_recent_observations(limit=10)
        claims = await self.store.find_recent_claims(limit=10)
        results = []
        for o in obs:
            results.append({"node": o, "kind": "observation"})
        for c in claims:
            results.append({"node": c, "kind": "claim"})
        return results

    async def _find_matching_node(self, description: str) -> dict | None:
        """Best-effort match a textual description to an existing node.

        Searches recent observations and claims for content overlap.
        """
        description_lower = description.lower()

        # Search observations
        for obs in await self.store.find_recent_observations(limit=20):
            raw = obs.get("raw_content", "").lower()
            if raw and _text_overlap(description_lower, raw):
                return obs

        # Search claims
        for claim in await self.store.find_recent_claims(limit=20):
            parts = [
                claim.get("subject_text", ""),
                claim.get("predicate_text", ""),
                claim.get("object_text", ""),
            ]
            combined = " ".join(parts).lower()
            if _text_overlap(description_lower, combined):
                return claim

        return None

    # -- Facade methods (satisfy MemoryAPI protocol) --

    async def get_recent_observations(self, limit: int = 10) -> list[dict[str, Any]]:
        return await self.store.find_recent_observations(limit=limit)

    async def get_recent_claims(self, limit: int = 20) -> list[dict[str, Any]]:
        return await self.store.find_recent_claims(limit=limit)

    async def get_unresolved_contradictions(
        self,
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        return await self.store.find_unresolved_contradictions()

    async def get_entities(self) -> list[dict[str, Any]]:
        return await self.store.query_by_type("Entity")

    async def infer(self, observation_text: str) -> str | None:
        """Use the LLM to produce an inference claim from an observation."""
        prompt = self._prompt_loader.load("inference_agent/infer")
        vars = InferenceVars(observation_text=observation_text)
        rendered = prompt.render(vars)

        response = await self.llm._client.messages.create(
            model=self.llm._model,
            max_tokens=256,
            system=rendered["system"] or "",
            messages=[{"role": "user", "content": rendered["user"] or ""}],
        )
        text = ""
        for block in response.content:
            if block.type == "text":
                text = block.text.strip()
                break
        if not text or text.upper().startswith("SKIP"):
            return None
        return text

    async def clear(self) -> None:
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
