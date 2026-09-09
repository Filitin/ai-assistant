# src/tools/timer.py
import subprocess
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _launch_window(total_seconds: int, label: str) -> None:
    subprocess.Popen(
        [
            sys.executable, "-m", "src.ui.timer_window",
            "--seconds", str(total_seconds),
            "--label", label,
        ],
        cwd=PROJECT_ROOT,
    )


def set_timer(minutes: int = 0, seconds: int = 0, label: str = "Timer") -> str:
    """
    Start a countdown timer. Opens a visual timer window.
    Provide minutes, seconds, or both. Examples: minutes=25, seconds=30, minutes=1 seconds=30.
    Minimum duration is 5 seconds. Maximum is 180 minutes.
    label: short description shown in the timer window and notification.
    """
    total_seconds = minutes * 60 + seconds
    if total_seconds < 5:
        raise ValueError(f"Timer must be at least 5 seconds, got {total_seconds}s")
    if total_seconds > 180 * 60:
        raise ValueError("Timer cannot exceed 180 minutes")

    thread = threading.Thread(
        target=_launch_window,
        args=(total_seconds, label),
        daemon=True,
    )
    thread.start()

    if minutes > 0 and seconds > 0:
        duration_str = f"{minutes} min {seconds} sec"
    elif minutes > 0:
        duration_str = f"{minutes} minute(s)"
    else:
        duration_str = f"{seconds} second(s)"

    return f"Timer set for {duration_str}."