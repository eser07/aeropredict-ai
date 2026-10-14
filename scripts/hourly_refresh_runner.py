#!/usr/bin/env python3
"""Run the expanded Aerodrome data refresh with a file lock and durable logs.

Intended to run once per hour via Windows Task Scheduler and WSL.
Never sends transactions and never starts a public web service.
"""
import fcntl
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOG_DIR = DATA / "hourly_refresh_logs"
LOCK_PATH = DATA / ".weekly_refresh.lock"  # Shared with the previous weekly runner
SCRIPT = ROOT / "scripts" / "refresh_expanded_data.py"
KEEP_LOGS = 168  # Approximately seven days of hourly results


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def main():
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logfile_path = LOG_DIR / (
        "refresh_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
        "_" + str(os.getpid()) + ".log"
    )
    with logfile_path.open("w", encoding="utf-8", buffering=1) as log:
        def write(message):
            print(f"[{utc_now()}] {message}", file=log, flush=True)

        write("AeroPredict AI | Windows hourly scheduled refresh")
        write(f"Repository: {ROOT}")
        write(f"Python: {sys.executable}")
        lock_fd = LOCK_PATH.open("a+")
        try:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                write("ERROR: Another scheduled refresh is already running; skipped.")
                return 2

            write("Starting 12-week FEES + backtest + BRIBES/USD + pairs refresh (hourly run)")
            with subprocess.Popen(
                [sys.executable, str(SCRIPT)],
                cwd=ROOT,
                stdout=log,
                stderr=subprocess.STDOUT,
            ) as child:
                status = child.wait()
            write(f"Refresh subprocess exit code: {status}")
            if status != 0:
                write("FAILED: The new dataset was not successfully published.")
            else:
                write("SUCCESS: All four expanded data components and the dashboard bundle were refreshed.")
            return status
        except Exception as exc:
            write(f"FAILED: {type(exc).__name__}: {exc}")
            return 1
        finally:
            try:
                fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            finally:
                lock_fd.close()
            for old in sorted(LOG_DIR.glob("refresh_*.log"), reverse=True)[KEEP_LOGS:]:
                try:
                    old.unlink()
                except OSError:
                    pass


if __name__ == "__main__":
    sys.exit(main())
