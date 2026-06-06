"""
Observability layer.

Every LLM call in the system funnels through src/llm.py. When a Tracer is
active (set via the `trace(...)` context manager), each call records its
label, the prompts it sent, the model's summarized thinking, the raw response,
and the parsed result. This turns the agent from a black box into an auditable
sequence of decisions: input → reasoning → output, per tool call.

Usage:
    from src.trace import trace

    with trace("diagnose case_02") as tr:
        gap = diagnose_learner(learner, graph)
        ...
    tr.save_json("trace.json")
    print(tr.render_markdown())
"""

from __future__ import annotations

import contextlib
import contextvars
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class LLMCall:
    label: str  # which decision this call drives, e.g. "diagnose", "plan", "judge:modality_fit"
    system: str
    user: str
    thinking: str  # the model's summarized reasoning (empty if thinking disabled)
    response_text: str  # raw text the model returned
    parsed: dict | None  # parsed Pydantic model as dict, when the call produced one
    elapsed_ms: float
    usage: dict  # token usage from the response
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class Tracer:
    title: str = ""
    calls: list[LLMCall] = field(default_factory=list)

    def record(self, call: LLMCall) -> None:
        self.calls.append(call)

    def to_dict(self) -> dict:
        return {"title": self.title, "calls": [asdict(c) for c in self.calls]}

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    def render_markdown(self) -> str:
        lines: list[str] = []
        if self.title:
            lines.append(f"# Trace: {self.title}\n")
        lines.append(
            f"_{len(self.calls)} LLM call(s). Each block shows what the agent "
            f"sent, how the model reasoned, and what came back._\n"
        )
        total_in = sum(c.usage.get("input_tokens", 0) for c in self.calls)
        total_out = sum(c.usage.get("output_tokens", 0) for c in self.calls)
        lines.append(
            f"**Totals:** {total_in:,} input tokens, {total_out:,} output tokens, "
            f"{sum(c.elapsed_ms for c in self.calls) / 1000:.1f}s wall.\n"
        )

        for i, c in enumerate(self.calls, 1):
            lines.append(f"\n## {i}. `{c.label}`  \n")
            lines.append(f"_{c.elapsed_ms / 1000:.1f}s · "
                         f"{c.usage.get('input_tokens', 0):,} in / "
                         f"{c.usage.get('output_tokens', 0):,} out_\n")

            if c.thinking.strip():
                lines.append("**Model reasoning (summarized):**\n")
                lines.append("> " + c.thinking.strip().replace("\n", "\n> ") + "\n")
            else:
                lines.append("_(thinking not captured for this call)_\n")

            if c.parsed is not None:
                lines.append("**Produced:**\n")
                lines.append("```json")
                lines.append(json.dumps(_salient(c.label, c.parsed), indent=2))
                lines.append("```\n")
            else:
                preview = c.response_text.strip()[:600]
                lines.append("**Returned:**\n")
                lines.append("```")
                lines.append(preview)
                lines.append("```\n")

            lines.append("<details><summary>prompt sent</summary>\n")
            lines.append("```")
            lines.append((c.system[:1500] + ("…" if len(c.system) > 1500 else "")))
            lines.append("--- user ---")
            lines.append((c.user[:1500] + ("…" if len(c.user) > 1500 else "")))
            lines.append("```")
            lines.append("</details>\n")
        return "\n".join(lines)


def _salient(label: str, parsed: dict) -> dict:
    """Trim parsed output to the fields that matter for the trace narrative."""
    if label == "diagnose":
        return {k: parsed.get(k) for k in (
            "target_concept_id", "suggested_difficulty", "confidence",
            "prerequisite_gaps", "rationale",
        )}
    if label == "plan":
        return {
            "target_concept_id": parsed.get("target_concept_id"),
            "modality": parsed.get("modality"),
            "rationale": parsed.get("rationale"),
            "steps": [
                {k: s.get(k) for k in ("step_number", "concept_id", "modality", "pedagogy_principle")}
                for s in parsed.get("steps", [])
            ],
        }
    if label.startswith("judge:"):
        return {k: parsed.get(k) for k in ("judge_name", "score", "rationale")}
    if label.startswith("generate:"):
        return {k: parsed.get(k) for k in ("type", "title")}
    return parsed


# --- active-tracer plumbing -------------------------------------------------

_active: contextvars.ContextVar[Tracer | None] = contextvars.ContextVar(
    "active_tracer", default=None
)


def get_active_tracer() -> Tracer | None:
    return _active.get()


@contextlib.contextmanager
def trace(title: str = ""):
    tracer = Tracer(title=title)
    token = _active.set(tracer)
    try:
        yield tracer
    finally:
        _active.reset(token)
