"""Start backend and frontend dev servers together."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = PROJECT_ROOT / "src" / "frontend"

BACKEND_HOST = os.getenv("BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = os.getenv("BACKEND_PORT", "8000")
FRONTEND_HOST = os.getenv("FRONTEND_HOST", "127.0.0.1")
FRONTEND_PORT = os.getenv("FRONTEND_PORT", "5174")


def start_backend() -> subprocess.Popen:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.api.app:app",
            "--app-dir",
            "src",
            "--host",
            BACKEND_HOST,
            "--port",
            BACKEND_PORT,
            "--reload",
        ],
        cwd=PROJECT_ROOT,
    )


def start_frontend() -> subprocess.Popen:
    env = os.environ.copy()
    env.setdefault("VITE_API_BASE_URL", f"http://{BACKEND_HOST}:{BACKEND_PORT}")
    return subprocess.Popen(
        [
            "npm",
            "run",
            "dev",
            "--",
            "--host",
            FRONTEND_HOST,
            "--port",
            FRONTEND_PORT,
        ],
        cwd=FRONTEND_DIR,
        env=env,
    )


def stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def main() -> int:
    print(f"Backend:  http://{BACKEND_HOST}:{BACKEND_PORT}")
    print(f"Frontend: http://{FRONTEND_HOST}:{FRONTEND_PORT}")
    print("Press Ctrl+C to stop both servers.")

    backend = start_backend()
    frontend = start_frontend()
    processes = [backend, frontend]

    try:
        while True:
            for process in processes:
                code = process.poll()
                if code is not None:
                    for other in processes:
                        if other is not process:
                            stop_process(other)
                    return code
            time.sleep(0.5)
    except KeyboardInterrupt:
        for process in processes:
            stop_process(process)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
