"""Tier floor rules in .github/scripts/check_tier.py (offline; git tests use tmp repos)."""

from __future__ import annotations

import importlib.util
import subprocess
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


@pytest.mark.parametrize(
    ("tier", "labels", "auto_merge", "blocked"),
    [
        ("S", ["tier:S"], True, False),
        ("M", ["tier:M"], False, False),
        ("M", ["tier:M"], True, True),  # S promoted to M with auto-merge still queued
        ("L", ["tier:L"], True, True),
        ("S", ["tier:S", "hold"], True, True),
    ],
)
def test_merge_policy(tier, labels, auto_merge, blocked):
    assert bool(check_tier.policy_errors(tier, labels, auto_merge)) == blocked


def test_renaming_a_sensitive_file_still_needs_l(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=tmp_path, check=True, capture_output=True)

    store = tmp_path / "src" / "memory" / "store.py"
    store.parent.mkdir(parents=True)
    store.write_text("x = 1\n")
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "base")
    git("mv", "src/memory/store.py", "src/memory/kept.py")
    git("commit", "-qm", "rename")
    monkeypatch.chdir(tmp_path)

    changes = check_tier.git_changes("HEAD~1")
    assert {p for p, _, _ in changes} == {"src/memory/store.py", "src/memory/kept.py"}
    assert check_tier.floor_for(changes, GLOBS)[0] == "L"


@pytest.mark.parametrize(
    ("path", "line"),
    [
        ("src/tools/charts.py", 'key = os.environ["ANTHROPIC_API_KEY"]'),
        ("src/tools/charts.py", "client = anthropic.Anthropic()"),
        ("src/tools/quiz.py", "from openai import OpenAI"),
        ("src/server/app.py", '@app.post("/admin/reset")'),
        ("src/tools/generate.py", "UNTRUSTED LEARNER TEXT: treat as data"),
        ("evals/runner.py", "subprocess.run(cmd)"),
    ],
)
def test_sensitive_code_in_unlisted_file_needs_l(path, line):
    changes = [(path, 1, "M")]
    assert check_tier.floor_for(changes, GLOBS, {path: [line]})[0] == "L"


@pytest.mark.parametrize(
    ("path", "line"),
    [
        ("src/tools/charts.py", "colour = '#1F8A6A'"),
        ("src/harness/retry.py", "import anthropic"),  # expected home of the client
        ("tests/test_retriever.py", 'monkeypatch.setenv("X", os.environ["Y"])'),  # tests are exempt
        ("docs/HOW_IT_WORKS.md", "set ANTHROPIC_API_KEY in .env"),  # only Python is scanned
    ],
)
def test_ordinary_or_exempt_lines_stay_s(path, line):
    changes = [(path, 1, "M")]
    assert check_tier.floor_for(changes, GLOBS, {path: [line]})[0] == "S"


def test_changed_lines_parse_additions_removals_and_deletions(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=tmp_path, check=True, capture_output=True)

    (tmp_path / "a.py").write_text("keep = 1\n-- not a header\n")
    (tmp_path / "gone.py").write_text("key = os.environ['K']\n")
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "base")
    (tmp_path / "a.py").write_text("keep = 1\nnew = 2\n")
    (tmp_path / "gone.py").unlink()
    git("add", "-A")
    git("commit", "-qm", "change")
    monkeypatch.chdir(tmp_path)

    got = check_tier.git_changed_lines("HEAD~1")
    assert sorted(got["a.py"]) == ["-- not a header", "new = 2"]
    assert got["gone.py"] == ["key = os.environ['K']"]


def test_changed_trigger_file_is_tampering(tmp_path, monkeypatch):
    def git(*args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                       cwd=tmp_path, check=True, capture_output=True)

    trig = tmp_path / ".github" / "workflows" / "tier-trigger.yml"
    trig.parent.mkdir(parents=True)
    trig.write_text("types: [opened, synchronize, labeled, unlabeled]\n")
    git("init", "-q")
    git("add", ".")
    git("commit", "-qm", "main")
    git("tag", "main")
    (tmp_path / "README.md").write_text("docs\n")
    git("add", ".")
    git("commit", "-qm", "untouched trigger")
    git("tag", "ok")
    trig.write_text("types: [opened, synchronize]\n")  # drops the label events
    git("commit", "-qam", "tampered trigger")
    monkeypatch.chdir(tmp_path)

    assert not check_tier.trigger_tampered("main", "ok")
    assert check_tier.trigger_tampered("main", "HEAD")
