"""Issue #99: timezone-aware ts on records; TestResult keeps failure and red-flag details."""

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src import schemas
from src.course import load_course

SAMPLE = Path(__file__).resolve().parent.parent / "courses" / "support_bot"
UTC_TS = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

BASE = {
    "Submission": dict(id="s1", task_id="t1", learner_id="l1", content="x"),
    "WalkthroughCheck": dict(submission_id="s1", kind="explain", passed=True),
    "TutorMoveLog": dict(session_id="se", move="hint", allowed=True, tokens=1, cost_usd=0.0),
    "TutorHelpLog": dict(session_id="se", task_id="t1", kind="hint"),
    "SkillUseLog": dict(learner_id="l1", skill_id="s", session_id="se",
                        help_used=False, unaided=True),
    "MasteryLog": dict(learner_id="l1", skill_id="s", confirmed=True),
}
NAMES = list(BASE)


def make(name, ts):
    return getattr(schemas, name)(**BASE[name], ts=ts)


@pytest.mark.parametrize("name", NAMES)
def test_record_accepts_utc_ts_and_round_trips(name):
    obj = make(name, UTC_TS)
    again = type(obj).model_validate_json(obj.model_dump_json())
    assert again == obj
    assert again.ts == UTC_TS
    assert again.ts.utcoffset() == timedelta(0)


@pytest.mark.parametrize("name", NAMES)
def test_non_utc_offset_is_converted_to_same_instant_in_utc(name):
    ist = timezone(timedelta(hours=5, minutes=30))
    obj = make(name, datetime(2026, 1, 2, 8, 34, 5, tzinfo=ist))
    assert obj.ts == UTC_TS
    assert obj.ts.utcoffset() == timedelta(0)
    assert obj.ts.hour == 3  # stored as UTC wall time, not +05:30


@pytest.mark.parametrize("name", NAMES)
def test_ts_without_timezone_raises(name):
    with pytest.raises(ValidationError):
        make(name, datetime(2026, 1, 2, 3, 4, 5))
    with pytest.raises(ValidationError):
        make(name, "2026-01-02T03:04:05")


def tr(**over):
    return schemas.TestResult(**{"submission_id": "s1", "passed": 1, "total": 2, **over})


def test_test_result_keeps_failure_and_red_flag_details_through_json():
    r = tr(failures=[{"test": "test_refund.py::test_x", "message": "assert 1 == 2"}],
           red_flags=[{"rule_id": "keyword_routing", "line": 12, "message": "keyword if"}])
    again = schemas.TestResult.model_validate_json(r.model_dump_json())
    assert again == r
    data = json.loads(r.model_dump_json())
    assert data["failures"] == [{"test": "test_refund.py::test_x", "message": "assert 1 == 2"}]
    assert data["red_flags"] == [{"rule_id": "keyword_routing", "line": 12,
                                  "message": "keyword if"}]


def test_red_flag_line_may_be_empty():
    r = tr(red_flags=[{"rule_id": "keyword_routing", "message": "m"}])
    assert r.red_flags[0].line is None
    r2 = tr(red_flags=[{"rule_id": "keyword_routing", "line": None, "message": "m"}])
    assert r2.red_flags[0].line is None


def test_failure_without_test_raises():
    with pytest.raises(ValidationError):
        tr(failures=[{"message": "no name"}])


def test_red_flag_without_rule_id_raises():
    with pytest.raises(ValidationError):
        tr(red_flags=[{"line": 3, "message": "no rule"}])


def test_old_string_failures_and_red_flags_are_rejected():
    with pytest.raises(ValidationError):
        tr(failures=["test_x"])
    with pytest.raises(ValidationError):
        tr(red_flags=["keyword_routing"])


@pytest.mark.parametrize("over", [dict(passed=3, total=2), dict(passed=-1), dict(total=-1)])
def test_test_result_still_rejects_passed_over_total_and_negative_counts(over):
    with pytest.raises(ValidationError):
        tr(**over)


def test_failing_reference_solution_returns_test_failure_with_id_and_message(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    dest = tmp_path / "course"
    shutil.copytree(SAMPLE, dest)
    ref = dest / "milestones" / "01_order_status" / "reference" / "support_agent.py"
    ref.write_text(ref.read_text() + "\n\ndef get_order_status(order_id):\n"
                   "    return 'WRONG'\n")
    results = load_course(dest).run_reference_solution()
    failures = results[0].failures
    assert failures, "a broken reference solution must report failures"
    assert results[0].passed < results[0].total
    for f in failures:
        assert isinstance(f, schemas.TestFailure)
        assert "test_order_status.py::" in f.test
        assert f.message.strip()
        assert "\n" not in f.message  # first line only


def test_sample_course_reference_solution_has_no_failures(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    for r in load_course(SAMPLE).run_reference_solution():
        assert r.failures == []
        assert r.passed == r.total > 0
