"""
Iteration budget for the agent loop.

Why this exists: the loop executes an LLM-authored workflow, and LLM-authored
plans are exactly the kind of thing that can run long — every extra step is
real latency and real spend. The budget makes the worst case boring:

  - While under budget, steps run normally.
  - On the *last* budgeted step, the loop injects a wrap-up instruction into
    artifact generation, so the session ends with consolidation rather than
    mid-thought.
  - At the cap, the loop force-terminates and emits a summary built from
    state it already has (learner model, steps completed) — no extra LLM
    call to say goodbye.

The cap counts *executed teaching steps* (generate→observe→adapt cycles),
not workflow re-plans, because steps are where the cost and the learner's
time go.
"""

from __future__ import annotations

import os

DEFAULT_MAX_STEPS = int(os.environ.get("ADAPTIVE_LEARNING_MAX_STEPS", "10"))


class IterationBudget:
    """Tracks executed steps against a configurable cap."""

    def __init__(self, max_steps: int = DEFAULT_MAX_STEPS):
        if max_steps < 1:
            raise ValueError("max_steps must be >= 1")
        self.max_steps = max_steps
        self.steps_executed = 0

    @property
    def exhausted(self) -> bool:
        """True once the cap is reached — the loop must terminate now."""
        return self.steps_executed >= self.max_steps

    @property
    def on_final_step(self) -> bool:
        """True while executing what must be the last step (cap − 1 done)."""
        return self.steps_executed == self.max_steps - 1

    def record_step(self) -> None:
        self.steps_executed += 1

    def summary(self) -> dict:
        return {
            "steps_executed": self.steps_executed,
            "max_steps": self.max_steps,
            "terminated_at_cap": self.exhausted,
        }
