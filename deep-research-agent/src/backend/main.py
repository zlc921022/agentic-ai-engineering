"""Compatibility entrypoint for local uvicorn runs.

The application implementation lives in ``backend.api.app``. Keeping this thin
module means existing commands like ``cd src/backend && uvicorn main:app`` still
work while the backend code is organized as a package.
"""

from __future__ import annotations

import sys
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from backend.api.app import app, create_app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
