#!/usr/bin/env python3
"""Keep the read-only AeroPredict AI expanded dashboard available in WSL.

Designed for a hidden Windows Task Scheduler "At log on" task. Does not
start, stop, or change the independent hourly FEES/BRIBES refresh task.
"""
import fcntl
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
LOCK_FILE = DATA / ".dashboard_server.lock"
LOG_FILE = DATA / "dashboard_server.log"
SERVER_SCRIPT = ROOT / "scripts" / "serve_dashboard.py"
HOST = "127.0.0.1"
PORT = 8765
RECHECK_SECONDS = 10


def occupied():
    """Do not steal a port used by a manually started server or another app."""
    try:
        with socket.create_connection((HOST, PORT), timeout=2):
            return True
    except OSError:
        return False


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8", buffering=1) as log:
        def notice(message):
            line = f"[{now()}] {message}"
            print(line, file=log, flush=True)

        lock = LOCK_FILE.open("a+")
        try:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                notice("Another dashboard supervisor already holds the lock; exiting.")
                return 0

            notice("AeroPredict AI dashboard supervisor started (expanded, localhost only).")
            previous_state = None
            while True:
                if occupied():
                    if previous_state != "port-occupied":
                        notice(
                            "Port 8765 is already in use; waiting for it to become free. "
                            "A manually started dashboard can keep serving meanwhile."
                        )
                    previous_state = "port-occupied"
                    time.sleep(RECHECK_SECONDS)
                    continue

                previous_state = "starting"
                notice("Launching local dashboard on http://127.0.0.1:8765/")
                try:
                    child = subprocess.Popen(
                        [sys.executable, str(SERVER_SCRIPT), "--dataset", "expanded"],
                        cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                    )
                    status = child.wait()
                    notice(f"Dashboard exited with code {status}; retrying in {RECHECK_SECONDS}s.")
                except (OSError, ValueError) as exc:
                    notice(f"Dashboard launch failed: {type(exc).__name__}: {exc}")
                time.sleep(RECHECK_SECONDS)
        except KeyboardInterrupt:
            notice("Dashboard supervisor interrupted.")
            return 0
        finally:
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            finally:
                lock.close()


if __name__ == "__main__":
    sys.exit(main())
