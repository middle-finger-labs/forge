#!/usr/bin/env python3
"""Start the Forge dashboard API server.

Usage::

    python -m api.run
    python api/run.py
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "api.server:app",
        host=os.environ.get("FORGE_API_HOST", "0.0.0.0"),
        port=int(os.environ.get("FORGE_API_PORT", "8000")),
        reload=True,
        log_level="info",
    )


if __name__ == "__main__":
    main()
