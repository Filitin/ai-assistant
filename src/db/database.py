import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent.parent.parent / "data" / "assistant.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema = f.read()
    conn.executescript(schema)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Items (tasks / notes)
# ---------------------------------------------------------------------------

def add_item(
    content: str,
    item_type: str = "task",
    due_date: str | None = None,
    language: str | None = None,
) -> int:
    """Add a new task or note. item_type: 'task' or 'note'. Returns new item id."""
    if item_type not in ("task", "note"):
        raise ValueError(f"item_type must be 'task' or 'note', got: {item_type}")
    conn = get_connection()
    cursor = conn.execute(
        "INSERT INTO items (type, content, due_date, language) VALUES (?, ?, ?, ?)",
        (item_type, content, due_date, language),
    )
    conn.commit()
    new_id = cursor.lastrowid
    conn.close()
    return new_id


def list_items(
    item_type: str | None = None,
    status: str = "pending",
) -> list[dict]:
    """Return list of tasks/notes. Default: only pending items. item_type=None returns both."""
    conn = get_connection()
    query = "SELECT * FROM items WHERE status = ?"
    params: list = [status]
    if item_type is not None:
        query += " AND type = ?"
        params.append(item_type)
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def update_item_status(item_id: int, new_status: str) -> bool:
    """Change item status to pending/done/archived. Returns True if found and updated."""
    if new_status not in ("pending", "done", "archived"):
        raise ValueError(f"Invalid status: {new_status}")
    conn = get_connection()
    cursor = conn.execute(
        "UPDATE items SET status = ?, updated_at = ? WHERE id = ?",
        (new_status, datetime.now(timezone.utc).isoformat(), item_id),
    )
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated


def touch_last_accessed(item_id: int) -> None:
    """Update last_accessed timestamp for an item (tracks 'where I left off')."""
    conn = get_connection()
    conn.execute(
        "UPDATE items SET last_accessed = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), item_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------

def create_session() -> str:
    """Create a new session record. Returns the session_id (UUID string)."""
    session_id = str(uuid.uuid4())
    conn = get_connection()
    conn.execute(
        "INSERT INTO sessions (id, started_at) VALUES (?, ?)",
        (session_id, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return session_id


def close_session(session_id: str, summary: str | None = None) -> None:
    """Mark a session as ended. Optionally store a summary string."""
    conn = get_connection()
    conn.execute(
        "UPDATE sessions SET ended_at = ?, summary = ? WHERE id = ?",
        (datetime.now(timezone.utc).isoformat(), summary, session_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Message history
# ---------------------------------------------------------------------------

def save_messages(session_id: str, messages: list[dict]) -> None:
    """
    Persist a list of message dicts to the messages table.
    Each dict must have 'role' and 'content' keys.
    tool_name is optional (used for role='tool' entries).
    Skips system messages — those are reconstructed fresh every run.
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            continue
        content = msg.get("content")
        # ollama tool call messages carry content=None and tool_calls list;
        # we store only the text-bearing turns for context reconstruction.
        # tool_calls themselves are ephemeral — the results are what matter.
        if content is None:
            continue
        tool_name = msg.get("tool_name")
        conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_name, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (session_id, role, str(content), tool_name, now),
        )
    conn.commit()
    conn.close()


def load_recent_messages(limit: int = 30) -> list[dict]:
    """
    Load the most recent `limit` messages across all sessions,
    ordered oldest-first so they slot directly into messages[] for ollama.
    Returns list of dicts with keys: role, content, tool_name.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT role, content, tool_name FROM messages
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    conn.close()

    # fetchall gives newest-first; reverse so ollama sees oldest-first
    result = []
    for row in reversed(rows):
        entry: dict = {"role": row["role"], "content": row["content"]}
        if row["tool_name"]:
            entry["tool_name"] = row["tool_name"]
        result.append(entry)
    return result


def get_last_session_summary() -> str | None:
    """
    Return the summary of the most recently closed session, if one exists.
    Used to inject a brief context paragraph at the start of a new session.
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT summary FROM sessions
        WHERE ended_at IS NOT NULL AND summary IS NOT NULL
        ORDER BY ended_at DESC
        LIMIT 1
        """,
    ).fetchone()
    conn.close()
    return row["summary"] if row else None


if __name__ == "__main__":
    init_db()
    print(f"Database initialized: {DB_PATH}")