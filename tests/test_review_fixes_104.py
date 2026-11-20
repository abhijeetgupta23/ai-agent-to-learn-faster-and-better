"""Codex review fixes on PR #104: skipped tests never count as passed; Jev spend is metered."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import typesafe_sdk
from src import llm
from src.checks import run_tests
from src.harness import cost
from src.schemas import MethodQuestion

REFUND = Path(__file__).resolve().parent.parent / "courses/support_bot/milestones/02_refund"


def test_skipped_tests_are_not_counted_as_passed():
    ref = (REFUND / "reference/support_agent.py").read_text()
    skipping = ref.replace(
        "def issue_refund(order_id, amount):",
        "def issue_refund(order_id, amount):\n    import pytest\n    pytest.skip('not implemented')\n",
        1,
    )
    assert skipping != ref
    tests = sorted((REFUND / "tests").glob("test_*.py"))
    passed, total, failures = run_tests(tests, "support_agent.py", skipping, runs=1)
    assert passed < total
    assert any(f.message.startswith("skipped") for f in failures)


def test_jev_spend_goes_to_the_active_meter_and_daily_counter(tmp_path, monkeypatch):
    monkeypatch.setattr(cost, "DAILY", cost.DailySpend(tmp_path / "daily.json"))

    class FakeClient:
        def system_one(self, state, questions, model):
            return SimpleNamespace(
                model="jev-test",
                nouls={qid: SimpleNamespace(noul=0.2) for qid in questions},
                usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=10),
            )

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", FakeClient)
    q = MethodQuestion(id="keyword_routing", question="Routes by keyword?", wrong_answer="yes")
    with cost.meter() as m:
        answers = llm.ask_jev("def f(): pass", [q])
    assert answers == {"keyword_routing": pytest.approx(0.2)}
    assert m.n_calls == 1 and m.total_usd > 0
    assert cost.DAILY.today_usd() == pytest.approx(m.total_usd)
