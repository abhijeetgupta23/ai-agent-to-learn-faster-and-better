"""Run the real app with a scripted stand-in for the model (no API key, no cost).

Only the model is faked; every tool, the agent loop, SSE and the frontend are
the real code. Responses come from the repo's recorded traces / golden graph,
plus one hand-written Socratic artifact (marked MOCK) for the teach step.
"""
import json, os, sys, time, types
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
os.environ.setdefault("ANTHROPIC_API_KEY", "replay-no-network")

from anthropic.types import Message, TextBlock, ToolUseBlock, Usage

TRACE = {c["label"]: c for c in json.load(open("docs/traces/case_02_struggling_use_socratic.json"))["calls"]}
GRAPH = json.load(open("evals/golden/graphs/cognitive_biases.json"))

SOCRATIC = {
    "type": "socratic",
    "title": "The 1-in-1,000 test (MOCK artifact for UI replay)",
    "opening": "A test for a rare disease is 99% accurate. You test positive. How worried should you be?",
    "dialogue": [
        {"role": "agent", "text": "Before answering: out of 1,000 people, how many actually have a disease that affects 1 in 1,000?"},
        {"role": "learner_prompt", "text": "Give a number."},
        {"role": "agent", "text": "Right, one. Now the test is wrong 1% of the time. Among the 999 healthy people, about how many test positive anyway?"},
        {"role": "learner_prompt", "text": "Estimate the false positives."},
        {"role": "agent", "text": "So roughly 10 healthy positives and 1 sick positive. Of everyone holding a positive result, what share is actually sick?"},
        {"role": "learner_prompt", "text": "Work out the fraction."},
    ],
    "target_insight": "A positive result from an accurate test can still mostly be wrong when the condition is rare, because the base rate dominates.",
}

def _usage():
    return Usage(input_tokens=1200, output_tokens=300, cache_read_input_tokens=0, cache_creation_input_tokens=0)

def _msg(content, stop):
    return Message(id="msg_replay", type="message", role="assistant", model="replay",
                   content=content, stop_reason=stop, stop_sequence=None, usage=_usage())

def _ev(kind, text):
    d = types.SimpleNamespace(type=kind, thinking=text if kind == "thinking_delta" else None,
                              text=text if kind == "text_delta" else None)
    return types.SimpleNamespace(type="content_block_delta", delta=d)

class _Stream:
    def __init__(self, thinking, final): self.thinking, self.final = thinking, final
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def __iter__(self):
        for w in self.thinking.split(" "):
            time.sleep(0.02); yield _ev("thinking_delta", w + " ")
    def get_final_message(self): return self.final

ORCH = [
    ("Learner failed base_rate_neglect twice via reading. Diagnose first.", "diagnose", {}),
    ("Gap confirmed: base_rate_neglect. Reading has failed twice, so plan the modality.", "plan_lessons", {}),
    ("Plan picks Socratic. Teach the core step.", "teach", {
        "concept_id": "base_rate_neglect", "modality": "socratic",
        "objective": "Surface the missing prior in the medical-test problem",
        "pedagogy_principle": "elaboration"}),
]

class _Messages:
    def stream(self, **kw):
        if kw.get("tools"):  # orchestrator
            n = sum(1 for m in kw["messages"] if m["role"] == "assistant")
            if n < len(ORCH):
                think, name, args = ORCH[n]
                return _Stream(think, _msg([ToolUseBlock(type="tool_use", id=f"tu_{n}", name=name, input=args)], "tool_use"))
            return _Stream("Lesson delivered. Wrap up.", _msg([TextBlock(type="text",
                text="Reading hasn't worked twice, so this time we'll reason it out together.")], "end_turn"))
        system = kw["system"][0]["text"]
        if "learning graph" in system.lower() and "extract" in system.lower():
            out = json.dumps(GRAPH)
        elif system.startswith("You are an expert tutor. Given a learner"):
            out = TRACE["diagnose"]["response_text"]
        elif "teaching workflow" in system:
            out = TRACE["plan"]["response_text"]
        elif "Socratic" in system:
            out = json.dumps(SOCRATIC)
        else:
            out = TRACE["generate:reading"]["response_text"]
        return _Stream("Working through the learner state and the subject map before deciding.",
                       _msg([TextBlock(type="text", text=out)], "end_turn"))

class FakeClient:
    messages = _Messages()

import src.llm, src.agent.autonomous
src.llm.get_client = lambda: FakeClient()
src.agent.autonomous.get_client = lambda: FakeClient()

import uvicorn
from src.server.app import app
uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", 8001)), log_level="warning")
