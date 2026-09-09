# src/reminders.py
"""
Background reminder checker. Run independently via Task Scheduler.
Checks due_date on pending tasks and fires banner notifications.

Notification schedule:
  -2 days  → auto banner "Due in 2 days"
  -1 day   → auto banner "Due tomorrow"
   0 days  → confirm banner "Due today — how did it go?" with Mark done button
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db.database import get_connection


def _today_utc() -> datetime:
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _parse_due(due_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(due_str[:19], fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _banner(title: str, message: str, mode: str = "auto", item_id: int | None = None) -> None:
    cmd = [
        sys.executable, "-m", "src.notify",
        "--title", title,
        "--message", message,
        "--mode", mode,
    ]
    if item_id is not None:
        cmd += ["--item-id", str(item_id)]
    subprocess.Popen(cmd, cwd=PROJECT_ROOT)


def check_reminders() -> None:
    today = _today_utc()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, content, due_date FROM items
        WHERE status = 'pending'
          AND due_date IS NOT NULL
        """,
    ).fetchall()
    conn.close()

    fired = 0
    for row in rows:
        due = _parse_due(row["due_date"])
        if due is None:
            continue

        due_date = due.replace(hour=0, minute=0, second=0, microsecond=0)
        delta_days = (due_date - today).days
        short = row["content"][:55] + ("..." if len(row["content"]) > 55 else "")

        if delta_days == 2:
            _banner(
                title="Reminder — due in 2 days",
                message=f"#{row['id']}: {short}",
                mode="auto",
            )
            fired += 1

        elif delta_days == 1:
            _banner(
                title="Reminder — due tomorrow",
                message=f"#{row['id']}: {short}",
                mode="auto",
            )
            fired += 1

        elif delta_days == 0:
            _banner(
                title="Due today — how did it go?",
                message=f"#{row['id']}: {short}",
                mode="confirm",
                item_id=row["id"],
            )
            fired += 1

    print(f"[reminders] Checked {len(rows)} tasks, fired {fired} notifications.")


if __name__ == "__main__":
    check_reminders()