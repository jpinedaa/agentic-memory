"""LLM translation layer using Anthropic Claude API.

Translates between natural language and structured graph operations.
Uses tool_use for structured extraction to guarantee valid JSON.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import anthropic

logger = logging.getLogger(__name__)


@dataclass
class Extraction:
    """A single extracted relationship from an observation."""

    subject: str
    predicate: str
    object: str


@dataclass
class ObservationData:
    """Structured data extracted from an observation text."""

    entities: list[str]
    extractions: list[Extraction]
    topics: list[str]


@dataclass
class ClaimData:
    """Structured data parsed from a claim text."""

    subject: str
    predicate: str
    object: str
    confidence: float
    basis_descriptions: list[str]
    supersedes_description: str | None = None
    contradicts_description: str | None = None


# -- Tool schemas for structured output --

OBSERVATION_TOOL = {
    "name": "record_observation",
    "description": "Record the structured data extracted from an observation.",
    "input_schema": {
        "type": "object",
        "properties": {
            "entities": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Entity names mentioned, lowercase (e.g. ['user', 'project alpha'])",
            },
            "extractions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subject": {"type": "string"},
                        "predicate": {"type": "string"},
                        "object": {"type": "string"},
                    },
                    "required": ["subject", "predicate", "object"],
                },
                "description": "Extracted relationships",
            },
            "topics": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Topic keywords",
            },
        },
        "required": ["entities", "extractions", "topics"],
    },
}

CLAIM_TOOL = {
    "name": "record_claim",
    "description": "Record the structured data parsed from a claim.",
    "input_schema": {
        "type": "object",
        "properties": {
            "subject": {"type": "string", "description": "The entity being described"},
            "predicate": {"type": "string", "description": "The relationship or attribute"},
            "object": {"type": "string", "description": "The value or target"},
            "confidence": {
                "type": "number",
                "description": "Certainty 0.0-1.0. Hedging language = lower, definitive = higher.",
            },
            "basis_descriptions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Descriptions of what this claim is based on",
            },
            "supersedes_description": {
                "type": ["string", "null"],
                "description": "If this replaces a previous claim, describe what it replaces. null otherwise.",
            },
            "contradicts_description": {
                "type": ["string", "null"],
                "description": "If this contradicts another claim, describe what it contradicts. null otherwise.",
            },
        },
        "required": ["subject", "predicate", "object", "confidence", "basis_descriptions"],
    },
}

OBSERVATION_SYSTEM = """\
You are a knowledge extraction system. Given an observation text, extract structured data \
by calling the record_observation tool.

Rules:
- Use lowercase for entity names
- Predicates should be simple verbs or verb phrases
- Keep objects concise
- Extract ALL meaningful relationships from the text"""

CLAIM_SYSTEM = """\
You are a knowledge graph claim parser. Given a claim text and context about existing \
knowledge, parse the claim by calling the record_claim tool.

Infer confidence from language: hedging = lower, definitive = higher."""

QUERY_GENERATION_PROMPT = """\
You are a knowledge graph query translator. Given a natural language question, generate a Cypher query to find relevant information in a Neo4j graph.

The graph has nodes with label :Node and these property conventions:
- id: UUID string
- type: "Observation", "Claim", "Resolution", or "Entity"
- source: who created this node
- timestamp: ISO8601 datetime string
- raw_content: original text (on Observations)
- name: entity name (on Entity nodes)
- confidence: float 0-1 (on Claims)
- subject_text, predicate_text, object_text: extracted relationship components

Relationships:
- SUBJECT: from Claim/Observation to Entity
- BASIS: from Claim to what it's based on
- SUPERSEDES: from newer Claim to older one it replaces
- CONTRADICTS: between conflicting Claims

Return ONLY a valid Cypher query string. No explanation, no markdown, no code fences.

Question: {query}"""

SYNTHESIS_PROMPT = """\
You are a knowledge synthesis system. Given a question and graph data retrieved from a knowledge store, produce a clear natural language answer.

Rules:
- Prioritize Resolution nodes over raw Claims
- Note when claims have been superseded
- Mention confidence levels when relevant
- If there are unresolved contradictions, mention them
- If no relevant data exists, say so clearly
- Be concise but complete

Question: {query}

Retrieved data:
{results}"""


class LLMTranslator:
    """Translates between natural language and graph structures using Claude."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def extract_observation(self, text: str) -> ObservationData:
        """Extract structured data from observation text using tool_use."""
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=OBSERVATION_SYSTEM,
            messages=[
                {"role": "user", "content": f"Extract structured data from this observation:\n\n{text}"}
            ],
            tools=[OBSERVATION_TOOL],
            tool_choice={"type": "tool", "name": "record_observation"},
        )
        data = self._extract_tool_input(response)
        return ObservationData(
            entities=data.get("entities", []),
            extractions=[Extraction(**e) for e in data.get("extractions", [])],
            topics=data.get("topics", []),
        )

    async def parse_claim(
        self, text: str, context: list[dict] | None = None
    ) -> ClaimData:
        """Parse a claim text into structured data using tool_use."""
        context_str = json.dumps(context, indent=2, default=str) if context else "No existing context."
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=CLAIM_SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Context about existing knowledge:\n{context_str}\n\n"
                        f"Claim text to parse:\n{text}"
                    ),
                }
            ],
            tools=[CLAIM_TOOL],
            tool_choice={"type": "tool", "name": "record_claim"},
        )
        data = self._extract_tool_input(response)
        return ClaimData(
            subject=data["subject"],
            predicate=data["predicate"],
            object=data["object"],
            confidence=float(data.get("confidence", 0.7)),
            basis_descriptions=data.get("basis_descriptions", []),
            supersedes_description=data.get("supersedes_description"),
            contradicts_description=data.get("contradicts_description"),
        )

    async def generate_query(self, text: str) -> str:
        """Translate a natural language question into a Cypher query."""
        prompt = QUERY_GENERATION_PROMPT.format(query=text)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        cypher = self._extract_text(response).strip()
        # Strip any markdown fencing the model might add
        if cypher.startswith("```"):
            lines = cypher.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            cypher = "\n".join(lines)
        return cypher

    async def synthesize_response(
        self, query: str, results: list[dict]
    ) -> str:
        """Turn graph query results into a natural language response."""
        prompt = SYNTHESIS_PROMPT.format(
            query=query, results=json.dumps(results, indent=2, default=str)
        )
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return self._extract_text(response)

    def _extract_text(self, response: anthropic.types.Message) -> str:
        """Extract text content from a Claude response."""
        for block in response.content:
            if block.type == "text":
                return block.text
        return ""

    def _extract_tool_input(self, response: anthropic.types.Message) -> dict:
        """Extract tool input from a tool_use response block."""
        for block in response.content:
            if block.type == "tool_use":
                return block.input
        raise ValueError(f"No tool_use block in response: {response.content}")
