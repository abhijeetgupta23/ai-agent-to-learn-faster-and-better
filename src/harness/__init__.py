"""
Failure-handling harness — the layer between the agent and an unreliable world.

The guardrails in the README's main section are *correctness* guardrails
(schema validation, difficulty clamps, prereq integrity). This package holds
the *failure-handling* guardrails:

  - retry.py  — bounded retries on transient external-call failures, and a
                structured error type for permanent ones, so a flaky network
                degrades a session instead of crashing it.
  - limits.py — an iteration budget for the agent loop, so a runaway workflow
                terminates gracefully with a summary instead of running
                (and spending) forever.

Everything here is deterministic and dependency-light by design: it is the
code that must keep working when everything else is failing.
"""

from src.harness.limits import IterationBudget
from src.harness.retry import ExternalCallError, call_with_retries, is_transient

__all__ = [
    "ExternalCallError",
    "IterationBudget",
    "call_with_retries",
    "is_transient",
]
