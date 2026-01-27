"""LLM translation layer using Anthropic Claude API.

Translates between natural language and structured graph operations.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import anthropic


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


OBSERVATION_EXTRACTION_PROMPT = """\
You are a knowledge extraction system. Given an observation text, extract structured data.

Return a JSON object with:
- "entities": list of entity names mentioned (e.g. ["user", "project alpha"])
- "extractions": list of relationships, each with "subject", "predicate", "object"
- "topics": list of topic keywords

Rules:
- Use lowercase for entity names
- Predicates should be simple verbs or verb phrases
- Keep objects concise
- Extract ALL meaningful relationships from the text

Example input: "user said they hate waking up early for meetings"
Example output:
{
  "entities": ["user"],
  "extractions": [
    {"subject": "user", "predicate": "expressed", "object": "dislike of early meetings"},
    {"subject": "user", "predicate": "mentioned", "object": "meetings"}
  ],
  "topics": ["meetings", "schedule", "morning"]
}
"""

CLAIM_PARSING_PROMPT = """\
You are a knowledge graph claim parser. Given a claim text and optional context about existing knowledge, parse the claim into structured data.

Return a JSON object with:
- "subject": the entity being described
- "predicate": the relationship or attribute
- "object": the value or target
- "confidence": float 0.0-1.0 (infer from language certainty; hedging = lower, definitive = higher)
- "basis_descriptions": list of descriptions of what this claim is based on (from the text)
- "supersedes_description": if this claim replaces a previous one, describe what it replaces (or null)
- "contradicts_description": if this claim contradicts another, describe what it contradicts (or null)

Context about existing knowledge (may be empty):
{context}

Claim text to parse:
{claim_text}
"""

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

Return ONLY a valid Cypher query string. The query should return relevant nodes.

Question: {query}
"""

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
{results}
"""


class LLMTranslator:
    """Translates between natural language and graph structures using Claude."""

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model

    async def extract_observation(self, text: str) -> ObservationData:
        """Extract structured data from observation text."""
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": f"Extract structured data from this observation:\n\n{text}",
                }
            ],
            system=OBSERVATION_EXTRACTION_PROMPT,
        )
        data = self._parse_json_response(response)
        return ObservationData(
            entities=data.get("entities", []),
            extractions=[
                Extraction(**e) for e in data.get("extractions", [])
            ],
            topics=data.get("topics", []),
        )

    async def parse_claim(
        self, text: str, context: list[dict] | None = None
    ) -> ClaimData:
        """Parse a claim text into structured data."""
        context_str = json.dumps(context, indent=2) if context else "No existing context."
        prompt = CLAIM_PARSING_PROMPT.format(
            context=context_str, claim_text=text
        )
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        data = self._parse_json_response(response)
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
        return self._extract_text(response).strip().strip("`")

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

    def _parse_json_response(self, response: anthropic.types.Message) -> dict:
        """Extract and parse JSON from a Claude response."""
        text = self._extract_text(response)
        # Handle markdown code blocks
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            text = text.split("```")[1].split("```")[0]
        return json.loads(text.strip())
