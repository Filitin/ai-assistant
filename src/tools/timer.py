# src/tools/timer.py
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


def set_timer(minutes: int = 0, seconds: int = 0, label: str = "Timer done") -> str:
    """
    Start a non-blocking countdown timer. Fires a banner notification when complete.
    Provide minutes, seconds, or both. Examples: minutes=1, seconds=30, minutes=1 seconds=30.
    Minimum duration is 5 seconds. Maximum is 180 minutes.
    label: short description shown in the notification.
    """
    total_seconds = minutes * 60 + seconds
    if total_seconds < 5:
        raise ValueError(f"Timer duration must be at least 5 seconds, got: {total_seconds}s")
    if total_seconds > 180 * 60:
        raise ValueError(f"Timer duration cannot exceed 180 minutes.")

    thread = threading.Thread(
        target=_run_timer,
        args=(total_seconds, label),
        daemon=True,
    )
    thread.start()

    # Human-readable confirmation
    if minutes > 0 and seconds > 0:
        duration_str = f"{minutes} min {seconds} sec"
    elif minutes > 0:
        duration_str = f"{minutes} minute(s)"
    else:
        duration_str = f"{seconds} second(s)"

    return f"Timer set for {duration_str}. Will notify when done."