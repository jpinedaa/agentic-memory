"""LLM translation layer using Anthropic Claude API.

Translates between natural language and structured graph operations.
Uses tool_use for structured extraction to guarantee valid JSON.
Prompts are loaded from YAML templates in prompts/ directory.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import anthropic

from src.prompts import (
    PromptLoader,
    ObservationVars,
    ClaimVars,
    QueryGenerationVars,
    SynthesisVars,
)

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

class LLMTranslator:
    """Translates between natural language and graph structures using Claude.

    Prompts are loaded from YAML templates in the prompts/ directory.
    """

    def __init__(self, api_key: str | None = None, model: str = "claude-sonnet-4-20250514") -> None:
        self._client = anthropic.AsyncAnthropic(api_key=api_key)
        self._model = model
        self._prompt_loader = PromptLoader()

    async def extract_observation(self, text: str) -> ObservationData:
        """Extract structured data from observation text using tool_use."""
        prompt = self._prompt_loader.load("llm_translator/observation")
        tpl_vars = ObservationVars(observation_text=text)
        rendered = prompt.render(tpl_vars)

        logger.debug("extract_observation: model=%s, text=%d chars", self._model, len(text))
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=rendered["system"] or "",
            messages=[
                {"role": "user", "content": f"Extract structured data from this observation:\n\n{text}"}
            ],
            tools=[OBSERVATION_TOOL],
            tool_choice={"type": "tool", "name": "record_observation"},
        )
        logger.debug(
            "extract_observation: stop_reason=%s, usage=%s",
            response.stop_reason, response.usage,
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
        prompt = self._prompt_loader.load("llm_translator/claim")
        tpl_vars = ClaimVars(claim_text=text, context=context or [])
        rendered = prompt.render(tpl_vars)

        logger.debug("parse_claim: model=%s, text=%d chars", self._model, len(text))
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=rendered["system"] or "",
            messages=[
                {
                    "role": "user",
                    "content": rendered["user"] or f"Parse this claim:\n{text}",
                }
            ],
            tools=[CLAIM_TOOL],
            tool_choice={"type": "tool", "name": "record_claim"},
        )
        logger.debug(
            "parse_claim: stop_reason=%s, usage=%s",
            response.stop_reason, response.usage,
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
        prompt = self._prompt_loader.load("llm_translator/query_generation")
        tpl_vars = QueryGenerationVars(query=text)
        rendered = prompt.render(tpl_vars)

        logger.debug("generate_query: model=%s, query=%s", self._model, text)
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=512,
            system=rendered["system"] or "",
            messages=[{"role": "user", "content": rendered["user"] or ""}],
        )
        logger.debug(
            "generate_query: stop_reason=%s, usage=%s",
            response.stop_reason, response.usage,
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
        prompt = self._prompt_loader.load("llm_translator/synthesis")
        tpl_vars = SynthesisVars(query=query, results=results)
        rendered = prompt.render(tpl_vars)

        logger.debug("synthesize_response: model=%s, results=%d rows", self._model, len(results))
        response = await self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=rendered["system"] or "",
            messages=[{"role": "user", "content": rendered["user"] or ""}],
        )
        logger.debug(
            "synthesize_response: stop_reason=%s, usage=%s",
            response.stop_reason, response.usage,
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
                logger.debug("tool_use: name=%s, keys=%s", block.name, list(block.input.keys()))
                return block.input
        raise ValueError(f"No tool_use block in response: {response.content}")
