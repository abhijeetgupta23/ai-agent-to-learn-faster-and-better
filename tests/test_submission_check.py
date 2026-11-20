"""Issue #101: test runner and Jev method check for a learner's submission.

Assumed public interface (the plan may rename; keep these in sync):
  - src.course.LoadedCourse.check_submission(submission, milestone_id, *, runs=3,
        timeout=60) -> TestResult        (timeout in seconds, per run)
  - src.course.LoadedCourse.check_method(submission, milestone_id, *,
        threshold=0.5) -> JudgeReview
  - src.course.CourseError for an unknown milestone id / bad course
  - Milestone.method_questions: list of objects with .id, .question, .wrong_answer
    ("yes" or "no"); course.json key `method_questions`
  - src.schemas.JudgeReview(submission_id, method_ok, issues, model);
    issues: list of JudgeIssue(question_id, probability)
  - src.llm.ask_jev(code: str, questions: list[MethodQuestion], *, model=...)
        -> dict[question_id, P(yes)]   (the one Jev call; tests monkeypatch it and
        the method check must call it as `llm.ask_jev` at call time)
  - src.llm.JEV_MODEL: str, the model name recorded in JudgeReview.model
  - src.llm.JevError: raised by the method check on any Jev failure
No LLM or network is used anywhere.
"""

import json
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from src import llm, schemas
from src.course import CourseError, load_course

SAMPLE = Path(__file__).resolve().parent.parent / "courses" / "support_bot"
REPO = SAMPLE.parent.parent
TS = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
REF = (SAMPLE / "milestones/02_refund/reference/support_agent.py").read_text()
M2 = "refund_tool"
TEST_FILE = "milestones/02_refund/tests/test_refund.py"
N_TESTS = len(re.findall(r"^def test_", (SAMPLE / TEST_FILE).read_text(), re.M))


@pytest.fixture(autouse=True)
def _no_keys(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)


def sub(content=REF, sid="s1"):
    return schemas.Submission(id=sid, task_id="task_refund", learner_id="l1",
                              content=content, ts=TS)


def course_copy(tmp_path, test_source=None):
    dest = tmp_path / "course"
    shutil.copytree(SAMPLE, dest, ignore=shutil.ignore_patterns("__pycache__"))
    if test_source is not None:
        (dest / TEST_FILE).write_text(test_source)
    return dest


def edit_json(dest, fn):
    path = dest / "course.json"
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


# ------------------------------------------------------------------ test runner


def test_check_returns_test_result_with_the_submission_id():
    r = load_course(SAMPLE).check_submission(sub(sid="sub-42"), M2, runs=1)
    assert isinstance(r, schemas.TestResult)
    assert r.submission_id == "sub-42"


def test_reference_solution_passes_every_test_on_every_run():
    r = load_course(SAMPLE).check_submission(sub(), M2)  # default 3 runs
    assert r.total == N_TESTS * 3
    assert r.passed == r.total
    assert r.failures == []


def test_number_of_runs_can_be_set():
    r = load_course(SAMPLE).check_submission(sub(), M2, runs=1)
    assert r.total == N_TESTS
    assert r.passed == r.total


def test_failing_code_names_each_failing_test_once_not_once_per_run():
    broken = REF.replace('if amount > order["total"]:', "if False:")
    assert broken != REF
    r = load_course(SAMPLE).check_submission(sub(broken), M2, runs=3)
    names = [f.test for f in r.failures]
    assert names, "the over-total test should fail"
    assert len(names) == len(set(names))
    assert any("over_order_total" in n for n in names)
    assert all(f.message.strip() for f in r.failures)
    assert r.passed < r.total


FLAKY_TEST = '''
from pathlib import Path
import support_agent  # noqa: F401

COUNT = Path(r"{count}")


def test_sometimes_fails():
    n = int(COUNT.read_text()) if COUNT.exists() else 0
    COUNT.write_text(str(n + 1))
    assert n >= 1, "first run fails"
'''


def test_flaky_test_is_a_failure_and_the_message_says_flaky(tmp_path):
    count = tmp_path / "count.txt"
    dest = course_copy(tmp_path, FLAKY_TEST.format(count=count))
    r = load_course(dest).check_submission(sub(), M2, runs=3)
    assert len(r.failures) == 1
    assert "flaky" in r.failures[0].message.lower()
    assert "test_sometimes_fails" in r.failures[0].test


def test_code_that_never_finishes_times_out_and_does_not_hang():
    start = time.monotonic()
    r = load_course(SAMPLE).check_submission(sub("while True:\n    pass\n"), M2,
                                             runs=1, timeout=3)
    assert time.monotonic() - start < 30
    assert r.failures
    assert any("timeout" in (f.test + f.message).lower() for f in r.failures)


def test_syntax_error_is_a_failure_not_an_exception():
    r = load_course(SAMPLE).check_submission(sub("def broken(:\n"), M2, runs=1)
    assert r.failures
    assert r.passed < r.total or r.total == 0


ENV_TEST = '''
import os
import support_agent  # noqa: F401


def test_no_secrets_in_env():
    assert "ANTHROPIC_API_KEY" not in os.environ
    assert "TYPESAFE_API_KEY" not in os.environ
'''


def test_code_runs_without_api_keys_in_its_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret-a")
    monkeypatch.setenv("TYPESAFE_API_KEY", "secret-b")
    dest = course_copy(tmp_path, ENV_TEST)
    r = load_course(dest).check_submission(sub(), M2, runs=1)
    assert r.total == 1 and r.passed == 1 and not r.failures


def _snapshot():
    return {str(p.relative_to(REPO)): p.stat().st_mtime_ns
            for p in REPO.rglob("*")
            if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts
            and ".pytest_cache" not in p.parts and ".ruff_cache" not in p.parts}


def test_her_code_does_not_change_any_file_in_the_repo():
    sneaky = REF + '\nopen("leaked_by_submission.txt", "w").write("x")\n'
    before = _snapshot()
    load_course(SAMPLE).check_submission(sub(sneaky), M2, runs=1)
    assert _snapshot() == before
    assert not (Path.cwd() / "leaked_by_submission.txt").exists()


def test_unknown_milestone_raises_course_error_naming_it():
    with pytest.raises(CourseError, match="no_such_milestone"):
        load_course(SAMPLE).check_submission(sub(), "no_such_milestone")


# ------------------------------------------------------------- method questions


def test_every_milestone_has_a_method_question_and_milestone_2_has_keyword_routing():
    course = load_course(SAMPLE)
    for m in course.milestones:
        assert len(m.method_questions) >= 1
        for q in m.method_questions:
            assert q.id and q.question and q.wrong_answer in ("yes", "no")
    m2 = next(m for m in course.milestones if m.id == M2)
    kr = next(q for q in m2.method_questions if q.id == "keyword_routing")
    assert kr.wrong_answer == "yes"


@pytest.mark.parametrize("field", ["id", "question", "wrong_answer"])
def test_method_question_missing_a_part_fails_to_load_naming_it(tmp_path, field):
    dest = course_copy(tmp_path)
    edit_json(dest, lambda d: d["milestones"][1]["method_questions"][0].pop(field))
    with pytest.raises(CourseError, match=field):
        load_course(dest)


# ------------------------------------------------------------------ Jev check


def fake_jev(monkeypatch, answers=None, default=0.05, calls=None):
    def fake(code, questions, **kw):
        if calls is not None:
            calls.append((code, list(questions), kw))
        return {q.id: (answers or {}).get(q.id, default) for q in questions}

    monkeypatch.setattr(llm, "ask_jev", fake)


def test_keyword_routing_at_094_gives_method_not_ok_with_one_issue(monkeypatch):
    fake_jev(monkeypatch, {"keyword_routing": 0.94})
    review = load_course(SAMPLE).check_method(sub(), M2)
    assert isinstance(review, schemas.JudgeReview)
    assert review.method_ok is False
    assert [i.question_id for i in review.issues] == ["keyword_routing"]
    assert review.issues[0].probability == pytest.approx(0.94)
    assert review.submission_id == "s1"


def test_answers_on_the_right_side_give_method_ok_and_no_issues(monkeypatch):
    fake_jev(monkeypatch, default=0.1)
    review = load_course(SAMPLE).check_method(sub(), M2)
    assert review.method_ok is True
    assert review.issues == []


def test_answer_exactly_at_the_threshold_counts_as_wrong(monkeypatch):
    fake_jev(monkeypatch, {"keyword_routing": 0.5})
    review = load_course(SAMPLE).check_method(sub(), M2)
    assert review.method_ok is False
    assert review.issues[0].question_id == "keyword_routing"
    fake_jev(monkeypatch, {"keyword_routing": 0.49})
    assert load_course(SAMPLE).check_method(sub(), M2).method_ok is True


def test_threshold_can_be_set(monkeypatch):
    fake_jev(monkeypatch, {"keyword_routing": 0.7})
    assert load_course(SAMPLE).check_method(sub(), M2, threshold=0.8).method_ok is True
    assert load_course(SAMPLE).check_method(sub(), M2, threshold=0.7).method_ok is False


def test_question_where_no_is_wrong_flags_low_probability(monkeypatch, tmp_path):
    dest = course_copy(tmp_path)
    edit_json(dest, lambda d: d["milestones"][1]["method_questions"][0].update(
        id="has_validation", wrong_answer="no"))
    fake_jev(monkeypatch, {"has_validation": 0.1})
    review = load_course(dest).check_method(sub(), M2)
    assert review.method_ok is False
    assert review.issues[0].question_id == "has_validation"
    assert review.issues[0].probability == pytest.approx(0.9)  # P(wrong answer)


def test_review_records_the_jev_model_name(monkeypatch):
    fake_jev(monkeypatch)
    review = load_course(SAMPLE).check_method(sub(), M2)
    assert review.model == llm.JEV_MODEL
    assert review.model


def test_all_questions_go_to_jev_in_one_call_as_text(monkeypatch):
    calls = []
    fake_jev(monkeypatch, calls=calls)
    course = load_course(SAMPLE)
    course.check_method(sub(), M2)
    assert len(calls) == 1
    code, questions, _ = calls[0]
    assert code == REF
    m2 = next(m for m in course.milestones if m.id == M2)
    assert [q.id for q in questions] == [q.id for q in m2.method_questions]


def test_method_check_never_runs_her_code(monkeypatch, tmp_path):
    marker = tmp_path / "ran.txt"
    code = f'open(r"{marker}", "w").write("x")\n'
    fake_jev(monkeypatch)
    load_course(SAMPLE).check_method(sub(code), M2)
    assert not marker.exists()


def _boom(exc):
    def fake(code, questions, **kw):
        raise exc

    return fake


def _unanswered(code, questions, **kw):
    return {q.id: 0.1 for q in questions[1:]}


@pytest.mark.parametrize("fake", [
    _boom(RuntimeError("api down")),
    _boom(TimeoutError("slow")),
    _unanswered,
    lambda code, questions, **kw: {q.id: 1.5 for q in questions},
    lambda code, questions, **kw: {q.id: -0.1 for q in questions},
    lambda code, questions, **kw: {q.id: float("nan") for q in questions},
], ids=["error", "timeout", "unanswered", "above_1", "below_0", "nan"])
def test_jev_failure_raises_and_never_reports_method_ok(monkeypatch, fake):
    monkeypatch.setattr(llm, "ask_jev", fake)
    with pytest.raises(llm.JevError):
        load_course(SAMPLE).check_method(sub(), M2)


def test_unknown_milestone_in_method_check_raises_course_error(monkeypatch):
    fake_jev(monkeypatch)
    with pytest.raises(CourseError, match="no_such_milestone"):
        load_course(SAMPLE).check_method(sub(), "no_such_milestone")


# ---------------------------------------------------------------------- clean-up


def test_red_flag_types_and_field_are_gone():
    assert not hasattr(schemas, "RedFlagRule")
    assert not hasattr(schemas, "RedFlag")
    assert "red_flags" not in schemas.TestResult.model_fields
    assert "red_flag_rules" not in schemas.Course.model_fields
    with pytest.raises(ValidationError):
        schemas.TestResult(submission_id="s1", passed=0, total=0, red_flags=[])


def test_course_json_with_red_flag_rules_fails_to_load(tmp_path):
    dest = course_copy(tmp_path)
    edit_json(dest, lambda d: d.update(red_flag_rules=[]))
    with pytest.raises(CourseError, match="red_flag_rules"):
        load_course(dest)


def test_shipped_course_json_has_no_red_flag_rules():
    assert "red_flag_rules" not in json.loads((SAMPLE / "course.json").read_text())
