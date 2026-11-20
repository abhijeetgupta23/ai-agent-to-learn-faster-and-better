"""Run a milestone's tests against a learner's code, in a throwaway folder.

Her code is untrusted: each check gets a fresh temp dir (deleted after), a
minimal environment with no API keys, and its own process group so a timeout
kills everything it started. Results come from pytest's junit XML, not stdout.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

from src.schemas import TestFailure


def _first_line(text: str | None) -> str:
    lines = (text or "").strip().splitlines()
    return lines[0].strip() if lines else "(no message)"


def _env(tmp: Path) -> dict[str, str]:
    return {"PATH": os.environ.get("PATH", os.defpath), "LANG": os.environ.get("LANG", "C.UTF-8"),
            "HOME": str(tmp), "PYTHONPATH": str(tmp), "CI": "1", "COLUMNS": "200",
            "PYTHONDONTWRITEBYTECODE": "1"}


def _parse_junit(xml_path: Path, stems: set[str]) -> list[tuple[str, str | None]]:
    """One (test id, error message or None) per test case in the junit file."""
    out: list[tuple[str, str | None]] = []
    for case in ET.parse(xml_path).getroot().iter("testcase"):
        cls, name = case.get("classname", ""), case.get("name", "")
        bad = case.find("failure")
        if bad is None:
            bad = case.find("error")
        msg = _first_line(bad.get("message") or bad.text) if bad is not None else None
        parts = cls.split(".") if cls else []
        if not parts or parts[0] not in stems:
            # Collection or import error: pytest reports it against the module.
            if msg is not None:
                out.append(("(collection)", msg))
            continue
        out.append((f"{parts[0]}.py::" + "::".join(parts[1:] + [name]), msg))
    return out


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_tests(test_files: list[Path], submission_file: str, content: str, *,
              runs: int = 3, timeout: int = 60) -> tuple[int, int, list[TestFailure]]:
    """Run `test_files` against `content` saved as `submission_file`, `runs` times.

    Returns (passed test-runs, total test-runs, one TestFailure per failing test).
    """
    tmp = Path(tempfile.mkdtemp(prefix="lf-check-"))
    try:
        names = []
        for f in test_files:
            shutil.copy(f, tmp / Path(f).name)
            names.append(Path(f).name)
        (tmp / submission_file).write_text(content)
        stems = {Path(n).stem for n in names}
        outcomes: dict[str, list[str | None]] = {}
        failures: list[TestFailure] = []
        for i in range(runs):
            xml_path = tmp / f"run{i}.xml"
            cmd = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                   f"--junitxml={xml_path}", *names]
            proc = subprocess.Popen(cmd, cwd=tmp, env=_env(tmp), start_new_session=True,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                _kill_group(proc)
                proc.wait()
                failures.append(TestFailure(test="(timeout)",
                                            message=f"timeout after {timeout}s (run {i + 1})"))
                break
            _kill_group(proc)  # anything her code left running
            try:
                cases = _parse_junit(xml_path, stems)
            except (OSError, ET.ParseError):
                outcomes.setdefault("(collection)", []).append("pytest produced no readable report")
                continue
            for tid, msg in cases:
                outcomes.setdefault(tid, []).append(msg)
        passed = total = 0
        for tid, results in outcomes.items():
            total += len(results)
            passed += sum(1 for r in results if r is None)
            errors = [r for r in results if r is not None]
            if not errors:
                continue
            if len(errors) == len(results):
                failures.append(TestFailure(test=tid, message=errors[0]))
            else:
                failures.append(TestFailure(
                    test=tid, message=f"flaky: passed {len(results) - len(errors)} of "
                                      f"{len(results)} runs; last error: {errors[-1]}"))
        return passed, total, failures
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
