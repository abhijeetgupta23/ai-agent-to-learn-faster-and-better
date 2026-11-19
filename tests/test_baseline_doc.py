"""Story #87: docs/baseline.md records dated baseline scores (offline, reads the doc only)."""
import re
from pathlib import Path

import pytest

DOC = Path(__file__).resolve().parent.parent / "docs" / "baseline.md"
DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


@pytest.fixture(scope="module")
def text() -> str:
    assert DOC.exists(), "docs/baseline.md is missing"
    return DOC.read_text(encoding="utf-8")


def _rows(text: str) -> list[str]:
    return [
        ln for ln in text.splitlines()
        if ln.strip().startswith("|") and not re.fullmatch(r"[|\s:-]+", ln.strip())
    ]


def _row(text: str, key: str) -> str:
    hits = [r for r in _rows(text) if key in r]
    assert hits, f"no table row for {key!r}"
    return hits[0]


def _is_not_run(row: str) -> bool:
    return "not run" in row.lower()


def _reason_after_not_run(row: str) -> str:
    m = re.search(r"not run[\s:;,\-—–]*(.*)", row, re.I)
    return re.sub(r"[|\s]", "", m.group(1)) if m else ""


def test_baseline_doc_opens_with_in_plain_words(text):
    head = "\n".join(text.strip().splitlines()[:5]).lower()
    assert "in plain words" in head


def test_pytest_row_has_date_sha_and_counts(text):
    row = _row(text, "pytest tests/")
    assert DATE.search(row)
    assert SHA.search(row)
    for word in ("passed", "failed", "skipped", "errors"):
        assert re.search(rf"\d+\s*{word}|{word}\W+\d+", row, re.I), f"missing {word} count"


def test_ruff_row_has_date_and_findings_count(text):
    row = _row(text, "ruff check .")
    assert DATE.search(row)
    assert re.search(r"\d+\s*findings?|findings?\W+\d+", row, re.I)


@pytest.mark.parametrize("entry", ["run_evals.py", "run_compare.py"])
def test_each_eval_entry_point_has_a_row_with_date_and_scores_or_reason(text, entry):
    row = _row(text, entry)
    assert DATE.search(row)
    if _is_not_run(row):
        assert _reason_after_not_run(row), "not run needs a reason"
    else:
        assert re.search(r"\d", re.sub(DATE, "", row)), "scored row needs a real number"


def test_every_row_carries_a_yyyy_mm_dd_date(text):
    keys = ("pytest tests/", "ruff check .", "run_evals.py", "run_compare.py")
    for key in keys:
        assert DATE.search(_row(text, key)), f"{key} row has no date"


def test_no_row_has_a_measurement_without_a_date_or_blank_not_run(text):
    measured = [r for r in _rows(text) if re.search(r"pytest|ruff|run_evals|run_compare", r)]
    assert measured
    for r in measured:
        assert DATE.search(r), f"undated row: {r}"
        if _is_not_run(r):
            assert _reason_after_not_run(r), f"empty reason: {r}"


def test_no_private_data_in_public_baseline(text):
    low = text.lower()
    assert "sk-ant" not in low
    assert "learner_id" not in low
    assert not re.search(r"\bspine\b.*[:=]\s*[\[{]", low)
