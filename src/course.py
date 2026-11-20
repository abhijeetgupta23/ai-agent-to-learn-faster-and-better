"""Course loader: read a course folder, validate it, run its reference solution.

`Course` itself lives in `src/schemas.py` (pure data). The loader returns a
`LoadedCourse`, a `Course` that also remembers its folder, so it can run the
milestone tests without adding file or subprocess code to the schema module.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import PrivateAttr, ValidationError

from src.checks import run_tests
from src.schemas import Course, Submission, TestResult

COURSE_FILE = "course.json"
TEST_TIMEOUT_SECONDS = 60


class CourseError(Exception):
    """A course folder is missing, malformed or incomplete. The message names the field."""


class LoadedCourse(Course):
    _root: Path = PrivateAttr()

    def run_reference_solution(self) -> list[TestResult]:
        """Run each milestone's tests against its reference solution (one result each)."""
        return [self._run_reference(m) for m in sorted(self.milestones, key=lambda m: m.order)]

    def _milestone(self, milestone_id: str):
        for m in self.milestones:
            if m.id == milestone_id:
                return m
        raise CourseError(f"unknown milestone: {milestone_id}")

    def _run(self, m, content: str, sid: str, runs: int, timeout: int) -> TestResult:
        passed, total, failures = run_tests([self._root / t for t in m.tests],
                                            m.submission_file, content,
                                            runs=runs, timeout=timeout)
        return TestResult(submission_id=sid, passed=passed, total=total, failures=failures)

    def _run_reference(self, m) -> TestResult:
        ref = self._root / m.reference_solution
        src = ref / m.submission_file if ref.is_dir() else ref
        if not src.is_file():
            raise CourseError(f"milestones.{m.id}.reference_solution: "
                              f"{m.submission_file} not found in {m.reference_solution}")
        return self._run(m, src.read_text(), f"reference:{m.id}", 1, TEST_TIMEOUT_SECONDS)

    def check_submission(self, submission: Submission, milestone_id: str, *,
                         runs: int = 3, timeout: int = TEST_TIMEOUT_SECONDS) -> TestResult:
        """Run the milestone's tests against her code, `runs` times, in a throwaway folder."""
        m = self._milestone(milestone_id)
        return self._run(m, submission.content, submission.id, runs, timeout)


def load_course(path: str | Path) -> LoadedCourse:
    """Load and validate `<path>/course.json`; raise CourseError naming what is wrong."""
    root = Path(path)
    file = root / COURSE_FILE
    if not file.is_file():
        raise CourseError(f"{COURSE_FILE} not found in {root}")
    try:
        data = json.loads(file.read_text())
    except json.JSONDecodeError as e:
        raise CourseError(f"{COURSE_FILE} is not valid JSON: {e}") from e
    try:
        course = LoadedCourse.model_validate(data)
    except ValidationError as e:
        problems = [f"{'.'.join(str(p) for p in err['loc']) or 'course'}: {err['msg']}"
                    for err in e.errors()]
        raise CourseError("; ".join(problems)) from e
    for m in course.milestones:
        for t in m.tests:
            if not (root / t).exists():
                raise CourseError(f"milestones.{m.id}.tests: file not found: {t}")
        if not (root / m.reference_solution).exists():
            raise CourseError(
                f"milestones.{m.id}.reference_solution: path not found: {m.reference_solution}")
    course._root = root
    return course
