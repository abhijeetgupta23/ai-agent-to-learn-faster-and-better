"""Convenience entry point: `python run_variance.py --k 3`.

Runs each golden case K times through the agent, scored by the deterministic
binary judges, and writes evals/results_variance.{md,json} with pass@k / pass^k.
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from evals.variance import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
