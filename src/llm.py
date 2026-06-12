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

import contextvars
import json
import os
import re
import time
from contextlib import contextmanager
from typing import Callable, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from src.harness import cost
from src.harness.retry import call_with_retries
from src.trace import LLMCall, get_active_tracer

T = TypeVar("T", bound=BaseModel)

DEFAULT_MODEL = os.environ.get("ADAPTIVE_LEARNING_MODEL", "claude-sonnet-4-6")

# Eval judges stay pinned to a strong Claude model regardless of which model
# the system under test runs on — otherwise a provider experiment (e.g.
# ADAPTIVE_LEARNING_MODEL=deepseek-reasoner) would also swap the graders and
# make scores incomparable across runs.
JUDGE_MODEL = os.environ.get("ADAPTIVE_LEARNING_JUDGE_MODEL", "claude-sonnet-4-6")

# Adaptive thinking with summarized display: the model decides how much to
# think, and we get a readable summary of that reasoning back. This is the
# single switch that makes the agent's "why" observable. Set
# ADAPTIVE_LEARNING_THINKING=off to disable (faster/cheaper, opaque).
THINKING_ENABLED = os.environ.get("ADAPTIVE_LEARNING_THINKING", "on").lower() != "off"
_THINKING = {"type": "adaptive", "display": "summarized"} if THINKING_ENABLED else {"type": "disabled"}


# When set, streaming deltas are forwarded here as they arrive, so a caller
# (e.g. the SSE endpoint) can surface live progress instead of waiting for the
# call to complete. The callback receives (kind, delta) where kind is
# "thinking" (summarized reasoning prose) or "text" (the model writing its
# answer — useful as a progress signal while JSON output is generated).
# Contextvar so concurrent requests don't see each other's stream.
_thinking_sink: contextvars.ContextVar[Callable[[str, str], None] | None] = contextvars.ContextVar(
    "thinking_sink", default=None
)


@contextmanager
def thinking_sink(callback: Callable[[str, str], None]):
    """Forward (kind, delta) streaming deltas from LLM calls in this context to `callback`."""
    token = _thinking_sink.set(callback)
    try:
        yield
    finally:
        _thinking_sink.reset(token)


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


def _generate(*, model: str, max_tokens: int, system: str, user: str) -> tuple[str, str, dict]:
    """
    One LLM round-trip, streamed; provider chosen by model name. Streaming
    (vs create) avoids HTTP timeouts on long generations and lets us forward
    thinking deltas to the active sink the moment they arrive.

    Returns (text, summarized_thinking, usage_dict) — provider-normalized.
    """
    if model.startswith("deepseek"):
        return _generate_deepseek(model=model, max_tokens=max_tokens, system=system, user=user)
    return _generate_anthropic(model=model, max_tokens=max_tokens, system=system, user=user)


def _generate_anthropic(*, model: str, max_tokens: int, system: str, user: str) -> tuple[str, str, dict]:
    sink = _thinking_sink.get()
    with get_client().messages.stream(
        model=model,
        max_tokens=max_tokens,
        thinking=_THINKING,
        system=system,
        messages=[{"role": "user", "content": user}],
    ) as stream:
        for event in stream:
            if sink is None or event.type != "content_block_delta":
                continue
            if event.delta.type == "thinking_delta" and event.delta.thinking:
                sink("thinking", event.delta.thinking)
            elif event.delta.type == "text_delta" and event.delta.text:
                sink("text", event.delta.text)
        response = stream.get_final_message()
    if response.stop_reason == "max_tokens":
        raise ValueError(
            f"LLM output truncated at max_tokens={max_tokens} (model={model}). "
            "Note adaptive-thinking tokens count toward the cap — raise "
            "max_tokens for this call."
        )
    text, thinking = _split_blocks(response)
    return text, thinking, _usage_dict(response)


# --- DeepSeek experiment (OpenAI-compatible API) -----------------------------
# Opt in by setting ADAPTIVE_LEARNING_MODEL=deepseek-chat or deepseek-reasoner
# plus DEEPSEEK_API_KEY. deepseek-reasoner streams its chain of thought as
# `reasoning_content` deltas, which map straight onto the thinking sink.

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

_deepseek_client = None


def get_deepseek_client():
    global _deepseek_client
    if _deepseek_client is None:
        from openai import OpenAI  # lazy: optional dependency, experiments only

        _deepseek_client = OpenAI(
            api_key=os.environ["DEEPSEEK_API_KEY"], base_url=DEEPSEEK_BASE_URL
        )
    return _deepseek_client


def _generate_deepseek(*, model: str, max_tokens: int, system: str, user: str) -> tuple[str, str, dict]:
    sink = _thinking_sink.get()
    # DeepSeek caps output tokens per model (chat: 8K, reasoner: 64K); requests
    # above the cap are rejected outright, so clamp rather than fail.
    max_tokens = min(max_tokens, 8192 if model == "deepseek-chat" else 65536)
    stream = get_deepseek_client().chat.completions.create(
        model=model,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        stream=True,
        stream_options={"include_usage": True},
    )
    text_parts: list[str] = []
    thinking_parts: list[str] = []
    usage = {"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0}
    finish_reason = None
    for chunk in stream:
        if chunk.choices:
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                thinking_parts.append(reasoning)
                if sink is not None:
                    sink("thinking", reasoning)
            if delta.content:
                text_parts.append(delta.content)
                if sink is not None:
                    sink("text", delta.content)
        if chunk.usage:
            details = getattr(chunk.usage, "prompt_tokens_details", None)
            usage = {
                "input_tokens": chunk.usage.prompt_tokens,
                "output_tokens": chunk.usage.completion_tokens,
                "cache_read_input_tokens": getattr(details, "cached_tokens", 0) or 0,
            }
    if finish_reason == "length":
        raise ValueError(
            f"LLM output truncated at max_tokens={max_tokens} (model={model}). "
            "Raise max_tokens for this call."
        )
    return "".join(text_parts), "".join(thinking_parts), usage


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
    Ask Claude for JSON conforming to a Pydantic schema.

    One repair round: if the output fails schema validation (e.g. an unescaped
    quote inside a JSON string — it happens), the model is shown its own
    output plus the validation error and asked to emit the corrected JSON.
    Fails fast only after that.

    `label` identifies which decision this call drives (e.g. "diagnose",
    "plan") and shows up in the trace.
    """
    schema_json = json.dumps(schema.model_json_schema(), indent=2)
    system_full = (
        f"{system}\n\n"
        f"Respond with valid JSON only, conforming to this schema:\n{schema_json}\n\n"
        "Do not include any prose, markdown fences, or commentary outside the JSON."
    )

    attempt_user = user
    error: Exception | None = None
    for attempt in ("", ":repair"):
        t0 = time.perf_counter()
        # Retries transient API failures (timeout/429/5xx) twice with linear
        # backoff; wraps permanent ones in ExternalCallError. See src/harness/retry.py.
        text, thinking, usage = call_with_retries(
            lambda: _generate(
                model=model, max_tokens=max_tokens, system=system_full, user=attempt_user
            ),
            label=f"llm:{label}{attempt}",
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        cost.record(model, usage)  # feeds per-session + daily budget caps

        parsed: T | None = None
        error = None
        try:
            parsed = schema.model_validate_json(_extract_json(text))
        except ValidationError as e:
            error = e

        tracer = get_active_tracer()
        if tracer is not None:
            tracer.record(
                LLMCall(
                    label=label + attempt,
                    system=system_full,
                    user=attempt_user,
                    thinking=thinking,
                    response_text=text,
                    parsed=(parsed.model_dump(mode="json") if parsed is not None else None),
                    elapsed_ms=elapsed_ms,
                    usage=usage,
                )
            )

        if error is None:
            return parsed
        attempt_user = (
            f"{user}\n\nYour previous response was not valid JSON for the schema. "
            f"Validation error:\n{error}\n\nPrevious response:\n{text}\n\n"
            "Emit the corrected JSON only — fix the error without changing the content."
        )

    raise ValueError(
        f"LLM output failed schema validation for {schema.__name__} "
        f"(label={label}) after a repair attempt:\n{text[:1000]}\n\n{error}"
    ) from error


def complete_text(
    system: str,
    user: str,
    *,
    label: str = "llm_call",
    model: str = DEFAULT_MODEL,
    max_tokens: int = 4000,
) -> str:
    t0 = time.perf_counter()
    text, thinking, usage = call_with_retries(
        lambda: _generate(model=model, max_tokens=max_tokens, system=system, user=user),
        label=f"llm:{label}",
    )
    elapsed_ms = (time.perf_counter() - t0) * 1000
    cost.record(model, usage)  # feeds per-session + daily budget caps

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
                usage=usage,
            )
        )
    return text


# ---------------------------------------------------------------------------
# Charts via Anthropic code execution (true PTC): the model WRITES matplotlib
# code and runs it in Anthropic's hosted sandbox; we retrieve the rendered PNG.
# No code executes on our infrastructure — the sandbox is Anthropic's.
# ---------------------------------------------------------------------------

CHARTS_ENABLED = os.environ.get("ADAPTIVE_LEARNING_CHARTS", "on").lower() != "off"
# Pinned to Sonnet independent of the pedagogy model: chart-writing is a
# code-gen task Sonnet does reliably (it completes the write→run→export tool
# dance), whereas Opus 4.8 tends to narrate and end its turn before the
# sandbox exports the figure. Also cheaper.
CHART_MODEL = os.environ.get("ADAPTIVE_LEARNING_CHART_MODEL", "claude-sonnet-4-6")
_CODE_EXEC_TOOL = {"type": "code_execution_20260120", "name": "code_execution"}


def _find_file_ids(obj) -> list[str]:
    """Collect every file_id anywhere in a model_dump'd response (dict/list tree)."""
    found: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "file_id" and isinstance(v, str):
                found.append(v)
            else:
                found.extend(_find_file_ids(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_find_file_ids(v))
    return found


def generate_chart_png(instruction: str, *, max_tokens: int = 4096) -> bytes | None:
    """
    Ask Claude to write+run matplotlib in its sandbox and return the PNG bytes,
    or None if no chart was produced (model declined, or anything went wrong —
    a missing chart must never break a lesson). Cost is metered like any call.
    """
    if not CHARTS_ENABLED:
        return None
    client = get_client()
    file_ids: list[str] = []
    # The model occasionally ends its turn after one bash step, before the
    # sandbox exports the saved figure as a downloadable file. Retry until a
    # file appears (or we give up — a missing chart never breaks a lesson).
    nudge = (
        "\n\nAfter saving the figure, run a SECOND bash command "
        "`ls -la /tmp/chart.png` so the sandbox captures and exports the file."
    )
    for attempt in range(3):
        try:
            response = client.messages.create(
                model=CHART_MODEL,
                max_tokens=max_tokens,
                tools=[_CODE_EXEC_TOOL],
                tool_choice={"type": "any"},  # force code execution, don't let it narrate
                messages=[{"role": "user", "content": instruction + nudge}],
                extra_headers={"anthropic-beta": "files-api-2025-04-14"},
            )
        except Exception:
            continue
        cost.record(CHART_MODEL, _usage_dict(response))
        file_ids = _find_file_ids(response.model_dump(warnings=False))
        if file_ids:
            break

    for file_id in file_ids:
        try:
            meta = client.beta.files.retrieve_metadata(file_id)
            mime = getattr(meta, "mime_type", "") or ""
            if mime and "image" not in mime:
                continue
            downloaded = client.beta.files.download(file_id)
            if hasattr(downloaded, "read"):
                return downloaded.read()
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
                tmp = tf.name
            downloaded.write_to_file(tmp)
            with open(tmp, "rb") as f:
                return f.read()
        except Exception:
            continue
    return None
