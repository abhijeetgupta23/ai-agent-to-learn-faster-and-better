"""Compute the minimum tier a PR's diff allows, and fail if its tier label is lower.

The label can always be raised by judgement (e.g. new behaviour makes a small
diff M); this check only stops a diff from being labelled *below* its floor.

It also blocks a merge while the PR carries a `hold` label, or while GitHub
auto-merge is on for anything but tier S (so promoting a queued S PR can't
slip it through).

Usage (CI): python check_tier.py --base <sha> --labels "a,b" --auto-merge true|false
CI runs this from the base branch (pull_request_target): the PR's commits are
only diffed, never executed, so a PR cannot change how it is graded.
Stdlib only, so the workflow needs no install step.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

TIERS = ["S", "M", "L"]
RULES_FILE = Path(__file__).resolve().parents[1] / "sensitive-paths.txt"

# S means a small fix in one area; above this many changed lines it is at least M.
S_MAX_LINES = 150


def load_globs(path: Path = RULES_FILE) -> list[str]:
    lines = (ln.split("#", 1)[0].strip() for ln in path.read_text().splitlines())
    return [ln for ln in lines if ln]


def glob_to_regex(glob: str) -> re.Pattern[str]:
    out = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def src_area(path: str) -> str | None:
    """The src/ package a file belongs to; top-level src/*.py count as one area."""
    parts = path.split("/")
    if parts[0] != "src":
        return None
    return parts[1] if len(parts) > 2 else "<src root>"


def floor_for(changes: list[tuple[str, int, str]], globs: list[str]) -> tuple[str, list[str]]:
    """changes: (path, changed_lines, git status letter). Returns (floor tier, reasons)."""
    patterns = [(g, glob_to_regex(g)) for g in globs]
    l_reasons: list[str] = []
    m_reasons: list[str] = []

    sensitive = sorted({p for p, _, _ in changes for g, rx in patterns if rx.match(p)})
    if sensitive:
        l_reasons.append("touches sensitive paths: " + ", ".join(sensitive))

    areas = sorted({a for p, _, _ in changes if (a := src_area(p))})
    if len(areas) > 1:
        l_reasons.append("cross-cutting: changes " + ", ".join(f"src/{a}" for a in areas))

    new_src = sorted(p for p, _, s in changes if s == "A" and p.startswith("src/") and p.endswith(".py"))
    if new_src:
        m_reasons.append("adds source files: " + ", ".join(new_src))

    total = sum(n for _, n, _ in changes)
    if total > S_MAX_LINES:
        m_reasons.append(f"{total} changed lines (S allows {S_MAX_LINES})")

    if l_reasons:
        return "L", l_reasons + m_reasons
    if m_reasons:
        return "M", m_reasons
    return "S", []


def tier_label(labels: list[str]) -> tuple[str | None, str | None]:
    """Returns (tier, error)."""
    tiers = sorted({lb.split(":", 1)[1] for lb in labels if lb.startswith("tier:")})
    tiers = [t for t in tiers if t in TIERS]
    if not tiers:
        return None, "PR has no tier label: add tier:S, tier:M or tier:L (copy it from the issue)."
    if len(tiers) > 1:
        return None, f"PR has several tier labels ({', '.join('tier:' + t for t in tiers)}); keep one."
    return tiers[0], None


def policy_errors(tier: str, labels: list[str], auto_merge: bool) -> list[str]:
    errors = []
    if "hold" in labels:
        errors.append("PR has the hold label: remove it to allow merging.")
    if auto_merge and tier != "S":
        errors.append(f"Auto-merge is on for a tier:{tier} PR: only tier S may auto-merge. "
                      "Disable auto-merge; M and L merge on the owner's instruction.")
    return errors


def git_changes(base: str, head: str = "HEAD") -> list[tuple[str, int, str]]:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout

    lines = {}
    for row in git("diff", "--numstat", "--no-renames", f"{base}...{head}").splitlines():
        added, deleted, path = row.split("\t", 2)
        # binary files report "-": count them as one line so they still register
        lines[path] = (int(added) if added != "-" else 1) + (int(deleted) if deleted != "-" else 0)
    status = {}
    for row in git("diff", "--name-status", "--no-renames", f"{base}...{head}").splitlines():
        s, path = row.split("\t", 1)
        status[path] = s[0]
    return [(p, n, status.get(p, "M")) for p, n in lines.items()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True, help="base commit to diff against")
    ap.add_argument("--head", default="HEAD", help="PR head commit to grade")
    ap.add_argument("--labels", default="", help="comma-separated PR labels")
    ap.add_argument("--auto-merge", default="false", help="true if GitHub auto-merge is on")
    ap.add_argument("--rules", type=Path, default=RULES_FILE, help="sensitive-paths file")
    args = ap.parse_args(argv)

    labels = [lb.strip() for lb in args.labels.split(",") if lb.strip()]
    tier, err = tier_label(labels)
    floor, reasons = floor_for(git_changes(args.base, args.head), load_globs(args.rules))

    print(f"Minimum tier for this diff: {floor}")
    for r in reasons:
        print(f"  - {r}")
    if err:
        print(f"::error::{err} This diff needs at least tier:{floor}.")
        return 1
    if TIERS.index(tier) < TIERS.index(floor):
        print(f"::error::Labelled tier:{tier} but the diff needs at least tier:{floor}. "
              f"Relabel the PR and its issue tier:{floor}.")
        return 1
    errors = policy_errors(tier, labels, args.auto_merge.lower() == "true")
    for e in errors:
        print(f"::error::{e}")
    if errors:
        return 1
    print(f"OK: labelled tier:{tier}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
