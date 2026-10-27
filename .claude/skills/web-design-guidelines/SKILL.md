---
name: web-design-guidelines
description: Review UI code for Web Interface Guidelines compliance. Use when asked to "review my UI", "check accessibility", "audit design", "review UX", or "check my site against best practices", and for the guidelines re-run in every frontend visual demo.
metadata:
  author: vercel
  version: "1.0.0"
  argument-hint: <file-or-pattern>
---

<!-- Adapted from vercel-labs/agent-skills (MIT, commit 6ec2693). Change: the rules are vendored in
     guidelines.md (vercel-labs/web-interface-guidelines command.md, MIT, commit 434b7f9) instead of
     fetched from GitHub on every run, so reviews are offline, pinned and reviewed. -->

# Web Interface Guidelines

Review files for compliance with Web Interface Guidelines.

## How It Works

1. Read the rules in `guidelines.md` next to this file (do not fetch them from the web).
2. Read the specified files (or ask which files to review).
3. Check against all rules in `guidelines.md`.
4. Output findings in the terse `file:line` format it describes.

## Usage

When a file or pattern is given:
1. Read `guidelines.md`
2. Read the specified files
3. Apply all rules
4. Output findings using the format specified in the guidelines

If no files are specified, ask which files to review. To refresh the rules, update `guidelines.md` in a PR.
