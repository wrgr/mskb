#!/usr/bin/env python3
"""
Build (and optionally serve) the MkDocs site without race conditions.

This script enforces:
1. Running from the project virtual environment by default.
2. Serialized site operations via a filesystem lock.
3. Sequential execution: `gen_site.py` -> `mkdocs build` -> optional `mkdocs serve`.
"""

from __future__ import annotations

import argparse
import atexit
import os
from pathlib import Path
import signal
import subprocess
import sys

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
        description="Generate docs and build MkDocs site sequentially with a lock."
    )
    parser.add_argument("--config", default="config.yaml", help="Pipeline config path.")
    parser.add_argument(
        "--strict", action="store_true", help="Pass --strict to mkdocs build."
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve site after a successful build (holds lock while serving).",
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="Host for mkdocs serve (default: 127.0.0.1)."
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port for mkdocs serve (default: 8000)."
    )
    parser.add_argument(
        "--allow-system-python",
        action="store_true",
        help="Allow running outside .venv (not recommended).",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    if not args.allow_system_python and not _in_project_venv(repo_root):
        raise SystemExit(
            "Refusing to run outside project venv. Use `.venv/bin/python site/build_site.py ...` "
            "or pass --allow-system-python."
        )

    lock_path = repo_root / "site" / ".build.lock"
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
    _run([python, "site/gen_site.py", "--config", args.config], cwd=repo_root)

    mkdocs_build_cmd = [python, "-m", "mkdocs", "build", "-f", "site/mkdocs.yml"]
    if args.strict:
        mkdocs_build_cmd.append("--strict")
    _run(mkdocs_build_cmd, cwd=repo_root)

    if args.serve:
        _run(
            [
                python,
                "-m",
                "mkdocs",
                "serve",
                "-f",
                "site/mkdocs.yml",
                "-a",
                f"{args.host}:{args.port}",
            ],
            cwd=repo_root,
        )


if __name__ == "__main__":
    main()
