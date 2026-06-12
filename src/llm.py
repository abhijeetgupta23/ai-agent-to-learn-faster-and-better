"""
Thin wrapper around the Anthropic SDK.

Centralizes:
  - model selection (so swapping models is one edit)
  - adaptive thinking with summarized display, so the model's reasoning is
    visible — this is what turns each decision from a verdict into something
    you can audit (see src/trace.py)
  - JSON-mode helper for tool-output parsing into Pydantic models
  - recording every call into the active Tracer when one is set
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from src.harness import cost
from src.harness.retry import call_with_retries
from src.trace import LLMCall, get_active_tracer

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.environ.get("ADAPTIVE_LEARNING_MODEL", "claude-opus-4-8")

# Adaptive thinking with summarized display: the model decides how much to
# think, and we get a readable summary of that reasoning back. This is the
# single switch that makes the agent's "why" observable. Set
# ADAPTIVE_LEARNING_THINKING=off to disable (faster/cheaper, opaque).
THINKING_ENABLED = os.environ.get("ADAPTIVE_LEARNING_THINKING", "on").lower() != "off"
_THINKING = {"type": "adaptive", "display": "summarized"} if THINKING_ENABLED else {"type": "disabled"}


_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = _maybe_wrap_langsmith(anthropic.Anthropic())
    return _client


def _maybe_wrap_langsmith(client: anthropic.Anthropic) -> anthropic.Anthropic:
    """
    Opt-in LangSmith tracing — purely config-driven, so enabling it on a host
    is setting env vars, not editing code. When LANGSMITH_TRACING (or the
    legacy LANGCHAIN_TRACING_V2) is truthy AND the langsmith package is present,
    wrap the Anthropic client so every call is traced; otherwise return it
    untouched. A missing package never breaks the app — tracing just stays off.
    """
    enabled = (
        os.environ.get("LANGSMITH_TRACING", "").lower() in ("1", "true", "yes")
        or os.environ.get("LANGCHAIN_TRACING_V2", "").lower() in ("1", "true", "yes")
    )
    if not enabled:
        return client
    try:
        from langsmith.wrappers import wrap_anthropic

        return wrap_anthropic(client)
    except Exception:
        # langsmith not installed or wrap failed — degrade silently to no tracing.
        return client


def _extract_json(text: str) -> str:
    """Pull JSON from a response that may have markdown fences or stray prose."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    obj = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if obj:
        return obj.group(1)
    return text


def _split_blocks(response) -> tuple[str, str]:
    """Return (text, summarized_thinking) from a response's content blocks."""
    text = "".join(b.text for b in response.content if b.type == "text")
    thinking = "".join(
        getattr(b, "thinking", "") for b in response.content if b.type == "thinking"
    )
    return text, thinking


def _usage_dict(response) -> dict:
    u = response.usage
    return {
        "input_tokens": getattr(u, "input_tokens", 0),
        "output_tokens": getattr(u, "output_tokens", 0),
        "cache_read_input_tokens": getattr(u, "cache_read_input_tokens", 0),
    }


def complete_json(
    system: str,
    user: str,
    schema: type[T],
    *,
    label: str = "llm_call",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 8000,
) -> T:
    """
    Ask Claude for JSON conforming to a Pydantic schema. Fails fast on bad output.

    `label` identifies which decision this call drives (e.g. "diagnose",
    "plan") and shows up in the trace.
    """
    client = get_client()
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    system_full = (
        f"{system}\n\n"
        f"Respond with valid JSON only, conforming to this schema:\n{schema_json}\n\n"
        "Do not include any prose, markdown fences, or commentary outside the JSON."
    )

    t0 = time.perf_counter()
    # Retries transient API failures (timeout/429/5xx) twice with linear
    # backoff; wraps permanent ones in ExternalCallError. See src/harness/retry.py.
    response = call_with_retries(
        lambda: client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking=_THINKING,
            system=system_full,
            messages=[{"role": "user", "content": user}],
        ),
        label=f"llm:{label}",
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    text, thinking = _split_blocks(response)
    cost.record(model, _usage_dict(response))  # feeds per-session + daily budget caps

    parsed: T | None = None
    error: Exception | None = None
    try:
        parsed = schema.model_validate_json(_extract_json(text))
    except ValidationError as e:
        error = e

    tracer = get_active_tracer()
    if tracer is not None:
        tracer.record(
            LLMCall(
                label=label,
                system=system_full,
                user=user,
                thinking=thinking,
                response_text=text,
                parsed=(parsed.model_dump(mode="json") if parsed is not None else None),
                elapsed_ms=elapsed_ms,
                usage=_usage_dict(response),
            )
        )

    if error is not None:
        raise ValueError(
            f"LLM output failed schema validation for {schema.__name__} "
            f"(label={label}):\n{text[:1000]}\n\n{error}"
        ) from error
    return parsed


def complete_text(
    system: str,
    user: str,
    *,
    label: str = "llm_call",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4000,
) -> str:
    client = get_client()
    t0 = time.perf_counter()
    response = call_with_retries(
        lambda: client.messages.create(
            model=model,
            max_tokens=max_tokens,
            thinking=_THINKING,
            system=system,
            messages=[{"role": "user", "content": user}],
        ),
        label=f"llm:{label}",
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    text, thinking = _split_blocks(response)
    cost.record(model, _usage_dict(response))  # feeds per-session + daily budget caps

    tracer = get_active_tracer()
    if tracer is not None:
        tracer.record(
            LLMCall(
                label=label,
                system=system,
                user=user,
                thinking=thinking,
                response_text=text,
                parsed=None,
                elapsed_ms=elapsed_ms,
                usage=_usage_dict(response),
            )
        )
    return text
