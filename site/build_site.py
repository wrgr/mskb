#!/usr/bin/env python3
"""
Build (and optionally serve) the MSKB Starlight site without race conditions.

This script enforces:
1. Running from the project virtual environment by default.
2. Serialized site operations via a filesystem lock.
3. Sequential execution: ``gen_site.py`` (writes topic pages + explorer JSON
   payloads into the Astro content/public directories) -> ``npm run build``
   -> optional ``astro preview``.
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

import fcntl


def _run(cmd: list[str], cwd: Path) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def _in_project_venv(repo_root: Path) -> bool:
    expected = (repo_root / ".venv").resolve()
    actual = Path(sys.prefix).resolve()
    return actual == expected


def _acquire_lock(lock_path: Path) -> tuple[int, bool]:
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return fd, False
    os.ftruncate(fd, 0)
    os.write(fd, f"{os.getpid()}\n".encode("utf-8"))
    return fd, True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate docs and build the Starlight site sequentially with a lock."
    )
    parser.add_argument("--config", default="config.yaml", help="Pipeline config path.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat Astro warnings as errors (passes CI=true to npm).",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run `astro dev` after a successful build (holds lock while serving).",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host for astro dev (default: 127.0.0.1)."
    )
    parser.add_argument(
        "--port", type=int, default=4321, help="Port for astro dev (default: 4321)."
    )
    parser.add_argument(
        "--allow-system-python",
        action="store_true",
        help="Allow running outside .venv (not recommended).",
    )
    parser.add_argument(
        "--skip-gen",
        action="store_true",
        help="Skip gen_site.py (build the existing content tree only).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    site_dir = repo_root / "site"

    if not args.allow_system_python and not _in_project_venv(repo_root):
        print(
            f"[build_site] WARNING: not running from {repo_root}/.venv "
            f"(sys.prefix={sys.prefix}). Continuing; pass --allow-system-python to silence."
        )

    if shutil.which("npm") is None:
        raise SystemExit("npm is required on PATH to build the Starlight site.")

    lock_path = site_dir / ".build.lock"
    lock_fd, acquired = _acquire_lock(lock_path)
    if not acquired:
        raise SystemExit(
            f"Another site build/serve is already running (lock: {lock_path}). "
            "Wait for it to finish and retry."
        )

    def _cleanup() -> None:
        try:
            os.close(lock_fd)
        except OSError:
            pass
        try:
            lock_path.unlink(missing_ok=True)
        except OSError:
            pass

    atexit.register(_cleanup)

    def _handle_signal(signum: int, _frame: object) -> None:
        _cleanup()
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    python = sys.executable
    if not args.skip_gen:
        _run([python, "site/gen_site.py", "--config", args.config], cwd=repo_root)

    if not (site_dir / "node_modules").exists():
        _run(["npm", "ci", "--no-audit", "--no-fund"], cwd=site_dir)

    env = os.environ.copy()
    if args.strict:
        env["CI"] = "true"
    print("+", "npm", "run", "build")
    subprocess.run(["npm", "run", "build"], cwd=site_dir, check=True, env=env)

    if args.serve:
        _run(
            [
                "npm",
                "run",
                "dev",
                "--",
                "--host",
                args.host,
                "--port",
                str(args.port),
            ],
            cwd=site_dir,
        )


if __name__ == "__main__":
    main()
