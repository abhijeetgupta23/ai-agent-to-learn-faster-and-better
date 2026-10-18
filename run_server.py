"""Convenience entry point: `python run_server.py`."""

import os

from dotenv import load_dotenv

load_dotenv()

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(
        "src.server.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
        reload=False,
    )
