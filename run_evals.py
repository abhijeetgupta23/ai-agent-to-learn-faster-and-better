"""Convenience entry point: `python run_evals.py`."""

import sys

from dotenv import load_dotenv

load_dotenv()

from evals.runner import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
