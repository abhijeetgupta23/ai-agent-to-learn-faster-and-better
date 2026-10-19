---
name: docs
description: Updates docs/ and README to match a branch diff (stage 8).
tools: Read, Grep, Glob, Edit, Write, Bash
model: sonnet
---
Read `git diff main...HEAD` and the affected docs (`docs/*.md`, README.md).
Update them to describe the merged behaviour, not the coding journey. Short,
plain words; prefer tables and diagrams over prose (see CLAUDE.md). Do not touch
code. Commit `docs(#<n>): <summary>` and push.
