"""
Offline tests for multi-provider support (src/llm.py provider registry, the
OpenAI-compatible tool loop plumbing in src/agent/autonomous.py, and pricing).

No API key, no network — these cover the pure routing/translation layers that
decide which provider a model id goes to and how tool calls round-trip.
"""

from __future__ import annotations

from types import SimpleNamespace

from src.agent.autonomous import TOOL_SCHEMAS, merge_tool_call_delta, openai_tool_schemas
from src.harness.cost import PRICING, price_for, usd_for
from src.llm import _clamp_output_tokens, provider_for


# ---------------------------------------------------------------------------
# provider routing
# ---------------------------------------------------------------------------

def test_provider_routing_by_model_prefix():
    assert provider_for("claude-sonnet-4-6") == "anthropic"
    assert provider_for("claude-opus-4-8") == "anthropic"
    assert provider_for("deepseek-chat") == "deepseek"
    assert provider_for("deepseek-reasoner") == "deepseek"
    assert provider_for("kimi-k2-thinking") == "moonshot"
    assert provider_for("kimi-k2-0905-preview") == "moonshot"
    assert provider_for("moonshot-v1-32k") == "moonshot"
    assert provider_for("gpt-5") == "openai"
    assert provider_for("gpt-4.1-mini") == "openai"
    assert provider_for("o3-mini") == "openai"


def test_unknown_model_defaults_to_anthropic():
    # Unknown ids fall through to the Anthropic client, which will reject them
    # loudly — better than silently picking some other provider.
    assert provider_for("llama-3.3-70b") == "anthropic"


def test_output_caps_clamp_by_prefix():
    assert _clamp_output_tokens("deepseek-chat", 32000) == 8192
    assert _clamp_output_tokens("deepseek-reasoner", 32000) == 32000
    assert _clamp_output_tokens("gpt-5", 32000) == 32000
    assert _clamp_output_tokens("kimi-k2-thinking", 32000) == 32000


# ---------------------------------------------------------------------------
# tool-schema translation (Anthropic -> OpenAI function calling)
# ---------------------------------------------------------------------------

def test_openai_tool_schemas_cover_all_tools():
    converted = openai_tool_schemas()
    assert [t["function"]["name"] for t in converted] == [t["name"] for t in TOOL_SCHEMAS]
    for orig, conv in zip(TOOL_SCHEMAS, converted):
        assert conv["type"] == "function"
        assert conv["function"]["description"] == orig["description"]
        # Parameters must be the same JSON schema the Anthropic path enforces.
        assert conv["function"]["parameters"] == orig["input_schema"]


# ---------------------------------------------------------------------------
# streamed tool-call accumulation
# ---------------------------------------------------------------------------

def _delta(index, id=None, name=None, arguments=None):
    return SimpleNamespace(
        index=index,
        id=id,
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def test_merge_tool_call_delta_accumulates_argument_fragments():
    pending: dict[int, dict] = {}
    # First chunk carries id + name, arguments arrive as string fragments.
    merge_tool_call_delta(pending, [_delta(0, id="call_1", name="teach")])
    merge_tool_call_delta(pending, [_delta(0, arguments='{"concept_id": ')])
    merge_tool_call_delta(pending, [_delta(0, arguments='"supply_demand"}')])
    assert pending == {
        0: {"id": "call_1", "name": "teach", "arguments": '{"concept_id": "supply_demand"}'}
    }


def test_merge_tool_call_delta_handles_parallel_calls():
    pending: dict[int, dict] = {}
    merge_tool_call_delta(pending, [
        _delta(0, id="call_a", name="diagnose", arguments="{}"),
        _delta(1, id="call_b", name="view_learner"),
    ])
    merge_tool_call_delta(pending, [_delta(1, arguments="{}")])
    assert pending[0] == {"id": "call_a", "name": "diagnose", "arguments": "{}"}
    assert pending[1] == {"id": "call_b", "name": "view_learner", "arguments": "{}"}


def test_merge_tool_call_delta_tolerates_empty_deltas():
    pending: dict[int, dict] = {}
    merge_tool_call_delta(pending, None)
    merge_tool_call_delta(pending, [])
    assert pending == {}


# ---------------------------------------------------------------------------
# pricing
# ---------------------------------------------------------------------------

def test_price_for_exact_and_prefix_match():
    assert price_for("deepseek-chat") == PRICING["deepseek-chat"]
    # Dated / suffixed ids resolve via longest-prefix.
    assert price_for("kimi-k2-0905-preview") == PRICING["kimi-k2"]
    assert price_for("kimi-k2-thinking-turbo") == PRICING["kimi-k2-thinking"]
    assert price_for("gpt-5-mini-2025-08-07") == PRICING["gpt-5-mini"]
    assert price_for("gpt-5-2025-08-07") == PRICING["gpt-5"]


def test_price_for_unknown_falls_back_to_opus():
    # Never under-count spend: unknown ids are billed at the priciest tier.
    assert price_for("some-future-model") == PRICING["claude-opus-4-8"]


def test_usd_for_uses_prefix_pricing():
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    assert usd_for(usage, "gpt-5-mini-2025-08-07") == PRICING["gpt-5-mini"]["in"]
