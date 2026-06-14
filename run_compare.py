"""Convenience entry point: `python run_compare.py`.

Runs the workflow-vs-autonomous head-to-head and writes
evals/results_comparison.{md,json}.
"""

import sys

from dotenv import load_dotenv

load_dotenv()

from evals.compare import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
