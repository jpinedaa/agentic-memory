"""Prompt template system with YAML files, Jinja2 rendering, and Pydantic validation.

Usage:
    from src.prompts import PromptLoader, ObservationVars

    loader = PromptLoader()
    prompt = loader.load("llm_translator/observation")

    vars = ObservationVars(observation_text="my girlfriend is ami")
    rendered = prompt.render(vars)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import logging

import yaml
from jinja2 import Environment, BaseLoader
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# -- Pydantic models for prompt variables --

class ObservationVars(BaseModel):
    """Variables for observation extraction prompts."""
    observation_text: str = Field(..., description="Raw observation text to extract from")


class ClaimVars(BaseModel):
    """Variables for claim parsing prompts."""
    claim_text: str = Field(..., description="The claim text to parse")
    context: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Recent claims and observations for context"
    )


class QueryGenerationVars(BaseModel):
    """Variables for Cypher query generation prompts."""
    query: str = Field(..., description="Natural language question to translate")


class SynthesisVars(BaseModel):
    """Variables for response synthesis prompts."""
    query: str = Field(..., description="The original question")
    results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Retrieved graph data"
    )


class InferenceVars(BaseModel):
    """Variables for inference generation prompts."""
    observation_text: str = Field(..., description="The observation to infer from")
    observation_id: str = Field(default="", description="ID of the observation node")
    include_reasoning: bool = Field(
        default=False,
        description="Whether to include step-by-step reasoning"
    )


class ValidationVars(BaseModel):
    """Variables for contradiction validation prompts."""
    claims: list[dict[str, Any]] = Field(..., description="Claims to check for contradictions")
    subject: str = Field(default="", description="Entity subject being validated")


# -- Prompt template classes --

class PromptTemplate:
    """A loaded and parsed prompt template."""

    def __init__(
        self,
        name: str,
        version: str,
        description: str,
        system: str | None,
        user: str | None,
        metadata: dict[str, Any],
        jinja_env: Environment,
    ) -> None:
        self.name = name
        self.version = version
        self.description = description
        self._system_template = system
        self._user_template = user
        self.metadata = metadata
        self._env = jinja_env

    def render(
        self,
        variables: BaseModel | dict[str, Any] | None = None,
    ) -> dict[str, str | None]:
        """Render the prompt with given variables.

        Args:
            variables: Pydantic model or dict of template variables

        Returns:
            Dict with 'system' and 'user' keys containing rendered strings
        """
        if variables is None:
            vars_dict = {}
        elif isinstance(variables, BaseModel):
            vars_dict = variables.model_dump()
        else:
            vars_dict = variables

        # Add metadata fields to available variables (for inheritance)
        vars_dict = {**self.metadata, **vars_dict}

        result = {
            "system": None,
            "user": None,
        }

        if self._system_template:
            template = self._env.from_string(self._system_template)
            result["system"] = template.render(**vars_dict)

        if self._user_template:
            template = self._env.from_string(self._user_template)
            result["user"] = template.render(**vars_dict)

        logger.debug(
            "render: template=%s, vars=%s, system=%d chars, user=%d chars",
            self.name,
            list(vars_dict.keys()),
            len(result["system"] or ""),
            len(result["user"] or ""),
        )
        return result

    def render_system(self, variables: BaseModel | dict[str, Any] | None = None) -> str:
        """Render only the system prompt."""
        rendered = self.render(variables)
        return rendered["system"] or ""

    def render_user(self, variables: BaseModel | dict[str, Any] | None = None) -> str:
        """Render only the user prompt."""
        rendered = self.render(variables)
        return rendered["user"] or ""


class PromptLoader:
    """Loads prompt templates from YAML files with inheritance support."""

    def __init__(self, prompts_dir: str | Path | None = None) -> None:
        if prompts_dir is None:
            # Default to prompts/ directory relative to project root
            self._base_path = Path(__file__).parent.parent / "prompts"
        else:
            self._base_path = Path(prompts_dir)

        self._cache: dict[str, dict[str, Any]] = {}
        self._env = Environment(
            loader=BaseLoader(),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def load(self, prompt_path: str) -> PromptTemplate:
        """Load a prompt template by path.

        Args:
            prompt_path: Path like "llm_translator/observation" (no .yaml extension)

        Returns:
            PromptTemplate ready for rendering
        """
        raw = self._load_raw(prompt_path)
        resolved = self._resolve_inheritance(raw)
        logger.debug("load: %s (version=%s)", prompt_path, resolved.get("version", "?"))

        return PromptTemplate(
            name=resolved.get("name", prompt_path),
            version=resolved.get("version", "unknown"),
            description=resolved.get("description", ""),
            system=resolved.get("system"),
            user=resolved.get("user"),
            metadata=resolved,
            jinja_env=self._env,
        )

    def _load_raw(self, prompt_path: str) -> dict[str, Any]:
        """Load raw YAML without resolving inheritance."""
        if prompt_path in self._cache:
            logger.debug("_load_raw: cache hit for %s", prompt_path)
            return self._cache[prompt_path]

        file_path = self._base_path / f"{prompt_path}.yaml"
        if not file_path.exists():
            raise FileNotFoundError(f"Prompt template not found: {file_path}")

        logger.debug("_load_raw: loading %s", file_path)
        with open(file_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)

        self._cache[prompt_path] = data
        return data

    def _resolve_inheritance(self, data: dict[str, Any]) -> dict[str, Any]:
        """Resolve 'extends' inheritance chain."""
        if "extends" not in data:
            return data

        parent_path = data["extends"]
        logger.debug("_resolve_inheritance: %s extends %s", data.get("name", "?"), parent_path)
        parent_raw = self._load_raw(parent_path)
        parent = self._resolve_inheritance(parent_raw)

        # Merge parent into child (child overrides parent)
        merged = {**parent, **data}

        # Remove extends from final result
        merged.pop("extends", None)

        return merged

    def list_prompts(self) -> list[str]:
        """List all available prompt paths."""
        prompts = []
        for root, dirs, files in os.walk(self._base_path):
            # Skip __pycache__ and hidden directories
            dirs[:] = [d for d in dirs if not d.startswith((".", "_"))]

            for file in files:
                if file.endswith(".yaml"):
                    rel_path = Path(root).relative_to(self._base_path)
                    prompt_name = file[:-5]  # Remove .yaml
                    if rel_path == Path("."):
                        prompts.append(prompt_name)
                    else:
                        prompts.append(f"{rel_path}/{prompt_name}")

        return sorted(prompts)


# -- Singleton loader for convenience --

_default_loader: PromptLoader | None = None  # pylint: disable=invalid-name  # lowercase _default_loader is conventional for private module state


def get_loader() -> PromptLoader:
    """Get the default prompt loader (singleton)."""
    global _default_loader  # pylint: disable=global-statement  # singleton getter requires global for module-level cache
    if _default_loader is None:
        _default_loader = PromptLoader()
    return _default_loader


def load_prompt(prompt_path: str) -> PromptTemplate:
    """Convenience function to load a prompt with the default loader."""
    return get_loader().load(prompt_path)
