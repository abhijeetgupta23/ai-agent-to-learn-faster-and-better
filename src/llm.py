"""
Thin wrapper around the Anthropic SDK.

Centralizes:
  - model selection (so swapping models is one edit)
  - adaptive thinking on by default (recommended for 4.7+)
  - JSON-mode helper for tool-output parsing into Pydantic models
"""

from __future__ import annotations

import json
import os
import re
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.environ.get("ADAPTIVE_LEARNING_MODEL", "claude-opus-4-8")


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic()
    return _client


def _extract_json(text: str) -> str:
    """Pull JSON from a response that may have markdown fences or stray prose."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    # Otherwise: first {...} or [...] block
    obj = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if obj:
        return obj.group(1)
    return text


def complete_json(
    system: str,
    user: str,
    schema: type[T],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8000,
) -> T:
    """
    Ask Claude for JSON conforming to a Pydantic schema. Fails fast on bad output.
    """
    client = get_client()
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    system_full = (
        f"{system}\n\n"
        f"Respond with valid JSON only, conforming to this schema:\n{schema_json}\n\n"
        "Do not include any prose, markdown fences, or commentary outside the JSON."
    )

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_full,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        return schema.model_validate_json(_extract_json(text))
    except ValidationError as e:
        raise ValueError(
            f"LLM output failed schema validation for {schema.__name__}:\n{text[:1000]}\n\n{e}"
        ) from e


def complete_text(
    system: str,
    user: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4000,
) -> str:
    client = get_client()
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in response.content if b.type == "text")
