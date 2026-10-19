"""Tier floor rules in .github/scripts/check_tier.py (offline, no git needed)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "check_tier.py"
_spec = importlib.util.spec_from_file_location("check_tier", _PATH)
check_tier = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_tier)

GLOBS = check_tier.load_globs()


def floor(*changes):
    return check_tier.floor_for(list(changes), GLOBS)[0]


@pytest.mark.parametrize(
    "path",
    [
        "src/harness/cost.py",
        "src/server/guards.py",
        "src/memory/store.py",
        "src/schemas.py",
        "src/llm.py",
        "src/graph/extractor.py",
        "tests/test_redteam_ingestion.py",
        "src/auth/session.py",
        "src/payments/stripe/webhook.py",
        "db/migrations/0001_init.sql",
        "Dockerfile",
        "pyproject.toml",
        ".github/workflows/ci.yml",
        ".github/sensitive-paths.txt",
    ],
)
def test_sensitive_path_needs_l(path):
    assert floor((path, 1, "M")) == "L"


def test_small_fix_in_one_area_is_s():
    assert floor(("src/tools/charts.py", 12, "M"), ("tests/test_retriever.py", 20, "M")) == "S"


def test_docs_only_is_s():
    assert floor(("docs/HOW_IT_WORKS.md", 80, "M"), ("README.md", 30, "M")) == "S"


def test_new_source_file_needs_m():
    assert floor(("src/tools/quiz.py", 40, "A")) == "M"


def test_large_diff_needs_m():
    assert floor(("src/tools/generate.py", check_tier.S_MAX_LINES + 1, "M")) == "M"


def test_two_src_packages_is_cross_cutting_l():
    assert floor(("src/tools/plan.py", 5, "M"), ("src/agent/autonomous.py", 5, "M")) == "L"


def test_glob_does_not_overmatch():
    # src/memory/** must not catch a sibling package with a similar name
    assert floor(("src/memoryviz/view.py", 3, "M")) == "S"


@pytest.mark.parametrize(
    ("labels", "tier", "has_error"),
    [
        (["story", "tier:M"], "M", False),
        (["story"], None, True),
        (["tier:S", "tier:L"], None, True),
    ],
)
def test_tier_label(labels, tier, has_error):
    got, err = check_tier.tier_label(labels)
    assert got == tier
    assert (err is not None) == has_error
