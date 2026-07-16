"""
Offline tests for the failure-handling harness (src/harness/).

No API key, no network: failures are simulated and sleeps are injected as
no-ops, so these exercise the retry/budget primitives in isolation.
"""

from __future__ import annotations

import httpx
import pytest

from src.harness import ExternalCallError, IterationBudget, call_with_retries, is_transient

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


def _anthropic_status_error(status: int, error_type: str):
    import anthropic

    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    resp = httpx.Response(status, request=req)
    body = {"type": "error", "error": {"type": error_type, "message": error_type}}
    return anthropic.APIStatusError(error_type, response=resp, body=body)


def test_overloaded_midstream_is_transient():
    # Anthropic overload arrives as an error event inside a 200 stream, so the
    # exception carries status 200, not 529 — must still be retried (regression).
    assert is_transient(_anthropic_status_error(200, "overloaded_error"))
    # A genuine 529 (status-based) is also transient.
    assert is_transient(_anthropic_status_error(529, "overloaded_error"))
    # A real 400 client error stays permanent.
    assert not is_transient(_anthropic_status_error(400, "invalid_request_error"))


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
