"""Issue #94: data model (11 records) and course format with the sample course.

Assumed public interface (the plan may rename; keep these in sync):
  - src.schemas: Learner, Skill, Task, Submission, WalkthroughCheck, TestResult,
    JudgeReview, TutorMoveLog, TutorHelpLog, SkillUseLog, MasteryLog
  - src.course: load_course(dir) -> Course, CourseError (raised on a bad course),
    Course.skills, Course.milestones[i].task.{skill_ids, brief.{why,...}},
    Course.run_reference_solution() -> list[TestResult], one per milestone
  - sample course on disk at courses/support_bot/course.json
No LLM is called anywhere; everything is offline.
"""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src import schemas
from src.course import CourseError, load_course

SAMPLE = Path(__file__).resolve().parent.parent / "courses" / "support_bot"
TS = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

VALID = {
    "Learner": dict(id="l1", prior_knowledge={}, current_course="support_bot",
                    current_milestone="order_status_tool"),
    "Skill": dict(id="tool_use", course="support_bot", needs=[], must_know=True,
                  first_learned_session=None),
    "Task": dict(id="t1", milestone="order_status_tool", skill_ids=["tool_use"],
                 brief=dict(why="w", done_looks_like="d", you_start_with="s")),
    "Submission": dict(id="s1", task_id="t1", learner_id="l1", content="print(1)",
                       content_type="code", ts=TS),
    "WalkthroughCheck": dict(submission_id="s1", kind="explain", passed=True, ts=TS),
    "TestResult": dict(submission_id="s1", passed=2, total=3, failures=[dict(test="t.py::q3", message="boom")]),
    "JudgeReview": dict(submission_id="s1", method_ok=False,
                        issues=[dict(question_id="keyword_routing", probability=0.9)],
                        model="judge-m"),
    "TutorMoveLog": dict(session_id="se1", move="hint", skill_id="tool_use",
                         gate="try_first_gate", allowed=False, reason="no attempt",
                         ts=TS, tokens=10, cost_usd=0.01),
    "TutorHelpLog": dict(session_id="se1", task_id="t1", kind="hint", ts=TS),
    "SkillUseLog": dict(learner_id="l1", skill_id="tool_use", session_id="se1",
                        gap_days=3, help_used=False, unaided=True, ts=TS),
    "MasteryLog": dict(learner_id="l1", skill_id="tool_use", confirmed=True, ts=TS),
}


def _model(name, **over):
    return getattr(schemas, name)(**{**VALID[name], **over})


@pytest.mark.parametrize("name", list(VALID))
def test_record_builds_and_round_trips_through_json(name):
    obj = _model(name)
    again = type(obj).model_validate_json(obj.model_dump_json())
    assert again == obj
    assert json.loads(obj.model_dump_json())  # snake_case JSON, non-empty


@pytest.mark.parametrize("name,field,good,bad", [
    ("WalkthroughCheck", "kind", ["explain", "change", "fix"], "hint"),
    ("TutorHelpLog", "kind", ["explain", "example", "hint", "fix"], "change"),
    ("TutorMoveLog", "gate",
     ["try_first_gate", "built_alone_gate", "progress_gate", "mastery_gate", ""],
     "gate_1"),
])
def test_enum_like_fields_accept_only_listed_values(name, field, good, bad):
    for value in good:
        assert getattr(_model(name, **{field: value}), field) == value
    with pytest.raises(ValidationError):
        _model(name, **{field: bad})


@pytest.mark.parametrize("name", list(VALID))
def test_missing_required_field_raises(name):
    required_gone = {k: v for k, v in VALID[name].items() if k != "id" and k != "submission_id"
                     and k != "session_id" and k != "learner_id"}
    key = next(k for k in ("id", "submission_id", "session_id", "learner_id")
               if k in VALID[name])
    with pytest.raises(ValidationError):
        getattr(schemas, name)(**required_gone)
    assert key  # the removed field was an identifying one


@pytest.mark.parametrize("name,field,bad", [
    ("Learner", "id", ["not", "a", "string"]),
    ("Submission", "ts", "not a date"),
    ("TestResult", "passed", "many"),
    ("TutorMoveLog", "allowed", "maybe"),
    ("SkillUseLog", "gap_days", "soon"),
    ("MasteryLog", "confirmed", "perhaps"),
])
def test_wrong_typed_field_raises(name, field, bad):
    with pytest.raises(ValidationError):
        _model(name, **{field: bad})


@pytest.mark.parametrize("over", [
    dict(passed=4, total=3),
    dict(passed=-1, total=3),
    dict(passed=0, total=-1),
])
def test_test_result_rejects_passed_over_total_and_negative_counts(over):
    with pytest.raises(ValidationError):
        _model("TestResult", **over)


def test_test_result_accepts_all_passed_and_zero():
    assert _model("TestResult", passed=3, total=3).passed == 3
    assert _model("TestResult", passed=0, total=0).total == 0


def _copy_course(tmp_path):
    dest = tmp_path / "course"
    shutil.copytree(SAMPLE, dest)
    return dest


def _edit(dest, fn):
    path = dest / "course.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


def test_skill_needing_unknown_skill_fails_to_load(tmp_path):
    dest = _copy_course(tmp_path)
    _edit(dest, lambda d: d["skills"][0].update(needs=["ghost_skill"]))
    with pytest.raises(CourseError, match="ghost_skill"):
        load_course(dest)


def test_sample_course_loads_with_two_milestones_in_order():
    course = load_course(SAMPLE)
    assert len(course.milestones) == 2
    first, second = (m.id for m in course.milestones)
    assert "order_status" in first
    assert "refund" in second


def test_every_milestone_brief_fields_are_non_empty():
    for m in load_course(SAMPLE).milestones:
        brief = m.task.brief
        assert brief.why.strip()
        assert brief.done_looks_like.strip()
        assert brief.you_start_with.strip()


def test_every_milestone_task_names_an_existing_skill():
    course = load_course(SAMPLE)
    known = {s.id for s in course.skills}
    for m in course.milestones:
        assert m.task.skill_ids
        assert set(m.task.skill_ids) <= known


def test_reference_solution_passes_every_test_offline(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    results = load_course(SAMPLE).run_reference_solution()
    assert len(results) == 2
    for r in results:
        assert r.total > 0
        assert r.passed == r.total


@pytest.mark.parametrize("missing,mutate", [
    ("tests", lambda d: d["milestones"][0].pop("tests")),
    ("judge_rubric", lambda d: d.pop("judge_rubric")),
    ("brief", lambda d: d["milestones"][1]["task"].pop("brief")),
])
def test_course_missing_a_required_part_fails_naming_it(tmp_path, missing, mutate):
    dest = _copy_course(tmp_path)
    _edit(dest, mutate)
    with pytest.raises(CourseError, match=missing):
        load_course(dest)


def test_only_the_two_milestone_demo_course_is_shipped():
    courses = Path(SAMPLE).parent
    assert [p.name for p in courses.iterdir() if p.is_dir()] == ["support_bot"]
    assert len(load_course(SAMPLE).milestones) == 2
