"""
Offline tests for the failure-handling harness (src/harness/).

No API key, no network: failures are simulated, sleeps are injected as no-ops,
and the agent-loop test monkeypatches the LLM-backed tools.
"""

from __future__ import annotations

import httpx
import pytest

import src.agent.loop as loop_mod
from src.agent.loop import run_session
from src.harness import ExternalCallError, IterationBudget, call_with_retries, is_transient
from src.schemas import (
    GapEstimate,
    LearnerModel,
    LearningGraph,
    Modality,
    ReadingArtifact,
    SessionTurn,
    Workflow,
    WorkflowStep,
)

NO_SLEEP = lambda s: None  # noqa: E731


# ---------------------------------------------------------------------------
# retry wrapper
# ---------------------------------------------------------------------------

def _transient_error() -> Exception:
    return httpx.ConnectTimeout("simulated timeout")


def test_transient_failure_is_retried_then_succeeds():
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _transient_error()
        return "ok"

    assert call_with_retries(flaky, label="t", sleep=NO_SLEEP) == "ok"
    assert calls["n"] == 3  # initial + 2 retries, then success


def test_transient_failure_exhausts_retries():
    calls = {"n": 0}

    def always_down():
        calls["n"] += 1
        raise _transient_error()

    with pytest.raises(ExternalCallError) as ei:
        call_with_retries(always_down, label="t", sleep=NO_SLEEP)
    assert calls["n"] == 3  # initial + exactly 2 retries
    assert ei.value.transient is True
    assert ei.value.attempts == 3


def test_permanent_failure_is_not_retried():
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise ValueError("bad request, will never work")

    with pytest.raises(ExternalCallError) as ei:
        call_with_retries(broken, label="t", sleep=NO_SLEEP)
    assert calls["n"] == 1
    assert ei.value.transient is False


def test_backoff_schedule_is_linear():
    waits: list[float] = []

    def always_down():
        raise _transient_error()

    with pytest.raises(ExternalCallError):
        call_with_retries(always_down, label="t", sleep=waits.append)
    assert waits == [1.0, 2.0]


def test_transient_classification():
    assert is_transient(httpx.ConnectError("boom"))
    assert is_transient(TimeoutError())
    assert not is_transient(ValueError("schema mismatch"))
    assert not is_transient(KeyError("missing"))


def test_error_payload_is_structured():
    err = ExternalCallError("llm:plan", attempts=3, transient=True, cause=TimeoutError("t"))
    payload = err.to_payload()
    assert payload["error"] == "external_call_failed"
    assert payload["label"] == "llm:plan"
    assert payload["attempts"] == 3
    assert payload["transient"] is True


# ---------------------------------------------------------------------------
# iteration budget
# ---------------------------------------------------------------------------

def test_budget_wrap_up_and_exhaustion():
    b = IterationBudget(max_steps=3)
    assert not b.on_final_step and not b.exhausted
    b.record_step()
    b.record_step()
    assert b.on_final_step and not b.exhausted  # executing step 3 of 3
    b.record_step()
    assert b.exhausted
    assert b.summary()["terminated_at_cap"] is True


def test_budget_rejects_nonpositive_cap():
    with pytest.raises(ValueError):
        IterationBudget(max_steps=0)


# ---------------------------------------------------------------------------
# agent loop under the budget (tools monkeypatched — no LLM)
# ---------------------------------------------------------------------------

_GRAPH = LearningGraph.model_validate_json(
    (__import__("pathlib").Path(__file__).parent.parent
     / "evals" / "golden" / "graphs" / "cognitive_biases.json").read_text()
)


def _fake_tools(monkeypatch, n_steps: int):
    learner = LearnerModel(user_id="u", domain_id=_GRAPH.domain_id)
    gap = GapEstimate(
        target_concept_id="base_rate",
        confidence=0.9,
        rationale="test",
        suggested_difficulty=1,
        prerequisite_gaps=[],
    )
    steps = [
        WorkflowStep(
            step_number=i + 1,
            concept_id="base_rate",
            modality=Modality.READING,
            objective="obj",
            pedagogy_principle="spaced repetition",
        )
        for i in range(n_steps)
    ]
    workflow = Workflow(
        target_concept_id="base_rate",
        modality=Modality.READING,
        steps=steps,
        rationale="r",
    )
    generated_with_wrap_up: list[bool] = []

    def fake_generate(step, concept, lrn, source_context=None, *, wrap_up=False):
        generated_with_wrap_up.append(wrap_up)
        return ReadingArtifact(title="t", body="b", key_takeaways=["k"])

    monkeypatch.setattr(loop_mod, "diagnose_learner", lambda l, g: gap)
    monkeypatch.setattr(loop_mod, "plan_workflow", lambda g, l, gr: workflow)
    monkeypatch.setattr(loop_mod, "generate_artifact", fake_generate)
    monkeypatch.setattr(loop_mod, "update_learner_model", lambda l, t, s=None: l)
    return learner, generated_with_wrap_up


def _respond(artifact, step) -> SessionTurn:
    return SessionTurn(concept_id=step.concept_id, modality=Modality.READING, correct=True)


def test_loop_caps_steps_and_injects_wrap_up(monkeypatch):
    learner, wrap_flags = _fake_tools(monkeypatch, n_steps=5)
    events = list(
        run_session(learner, _GRAPH, on_learner_response=_respond, max_steps=3)
    )
    types = [e.type for e in events]
    assert types.count("artifact") == 3  # capped: 3 of 5 planned steps ran
    assert wrap_flags == [False, False, True]  # wrap-up injected on the last one
    assert "budget_exhausted" in types
    assert types[-1] == "done"  # graceful termination, with summary
    done = events[-1].payload
    assert done["budget"]["terminated_at_cap"] is True


def test_loop_under_cap_is_unaffected(monkeypatch):
    learner, wrap_flags = _fake_tools(monkeypatch, n_steps=2)
    events = list(
        run_session(learner, _GRAPH, on_learner_response=_respond, max_steps=10)
    )
    types = [e.type for e in events]
    assert types.count("artifact") == 2
    assert wrap_flags == [False, False]
    assert "budget_exhausted" not in types
    assert types[-1] == "done"


def test_loop_handles_external_call_failure_gracefully(monkeypatch):
    learner, _ = _fake_tools(monkeypatch, n_steps=2)
    err = ExternalCallError("llm:plan", attempts=3, transient=True, cause=TimeoutError("t"))

    def failing_plan(g, l, gr):
        raise err

    monkeypatch.setattr(loop_mod, "plan_workflow", failing_plan)
    events = list(
        run_session(learner, _GRAPH, on_learner_response=_respond, max_steps=10)
    )
    types = [e.type for e in events]
    assert "error" in types
    error_event = next(e for e in events if e.type == "error")
    assert error_event.payload["error"] == "external_call_failed"
    assert types[-1] == "done"  # session ends gracefully, never raises
    assert events[-1].payload["terminated_by"] == "external_call_failure"
