# src/tools/timer.py
"""
Non-blocking countdown timer.
Fires a banner notification via src.notify when complete.
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _run_timer(seconds: int, label: str) -> None:
    time.sleep(seconds)
    subprocess.Popen(
        [
            sys.executable, "-m", "src.notify",
            "--title", "Timer complete",
            "--message", label,
            "--mode", "auto",
        ],
        cwd=PROJECT_ROOT,
    )


def set_timer(minutes: int, label: str = "Timer done") -> str:
    """
    Start a non-blocking countdown timer.
    Shows a banner notification when complete.
    minutes: duration in minutes (1-180).
    label: what to show in the notification banner.
    """
    if not (1 <= minutes <= 180):
        raise ValueError(f"minutes must be between 1 and 180, got: {minutes}")

    seconds = minutes * 60
    thread = threading.Thread(
        target=_run_timer,
        args=(seconds, label),
        daemon=True,
    )
    thread.start()
    return f"Timer set for {minutes} minute(s). Will notify when done."