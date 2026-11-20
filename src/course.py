"""Course loader: read a course folder, validate it, run its reference solution.

`Course` itself lives in `src/schemas.py` (pure data). The loader returns a
`LoadedCourse`, a `Course` that also remembers its folder, so it can run the
milestone tests without adding file or subprocess code to the schema module.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from pydantic import PrivateAttr, ValidationError

from src.schemas import Course, TestResult

COURSE_FILE = "course.json"
TEST_TIMEOUT_SECONDS = 60


class CourseError(Exception):
    """A course folder is missing, malformed or incomplete. The message names the field."""


class LoadedCourse(Course):
    _root: Path = PrivateAttr()

    def run_reference_solution(self) -> list[TestResult]:
        """Run each milestone's tests against its reference solution (one result each)."""
        return [self._run_milestone(m) for m in sorted(self.milestones, key=lambda m: m.order)]

    def _run_milestone(self, m) -> TestResult:
        ref = self._root / m.reference_solution
        ref_dir = ref if ref.is_dir() else ref.parent
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        env["PYTHONPATH"] = os.pathsep.join(
            [str(ref_dir)] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])
        )
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rf",
               *[str(self._root / t) for t in m.tests]]
        sid = f"reference:{m.id}"
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env,
                                  cwd=self._root, timeout=TEST_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            return TestResult(submission_id=sid, passed=0, total=0,
                              failures=[f"timeout after {TEST_TIMEOUT_SECONDS}s"])
        return _parse_pytest(sid, proc.stdout + proc.stderr)


def _parse_pytest(submission_id: str, out: str) -> TestResult:
    # Use the last pytest summary line, not the last line of output: warnings or
    # plugins can print after it (or to stderr), which hid the summary in CI.
    summary = re.compile(r"\b\d+ (?:passed|failed|errors?)\b")
    lines = [ln for ln in out.splitlines() if summary.search(ln)]
    last = lines[-1] if lines else ""

    def count(word: str) -> int:
        return sum(int(n) for n in re.findall(rf"(\d+) {word}\b", last))

    passed = count("passed")
    failed = count("failed") + count("errors?")
    failures = [m.group(1) for m in re.finditer(r"^(?:FAILED|ERROR) (\S+)", out, re.M)]
    if not last:
        tail = " | ".join(out.strip().splitlines()[-5:])
        failures.append(f"no pytest summary in output: {tail[:300]}")
    return TestResult(submission_id=submission_id, passed=passed, total=passed + failed,
                      failures=failures)


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
