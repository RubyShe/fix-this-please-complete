import fcntl
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data" / "classification" / "state.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS classification (
    session_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    labels TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost REAL,
    model TEXT
);
CREATE TABLE IF NOT EXISTS queue (
    session_id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS queue_pending_session
    ON queue(session_id) WHERE status = 'pending';
"""


def open_state(path: Path | None = None) -> tuple[sqlite3.Connection, object]:
    """Open state.db and hold an exclusive lock until the returned file is closed."""
    database = STATE_PATH if path is None else path
    database.parent.mkdir(parents=True, exist_ok=True)
    lock_file = open(database.with_name(database.name + ".lock"), "a+")
    print(f"Waiting for {database.name}", flush=True)
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    print(f"Locked {database}", flush=True)
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(SCHEMA)
    classification_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(classification)")
    }
    if "input_tokens" not in classification_columns:
        connection.execute("ALTER TABLE classification ADD COLUMN input_tokens INTEGER")
    if "output_tokens" not in classification_columns:
        connection.execute("ALTER TABLE classification ADD COLUMN output_tokens INTEGER")
    if "error" in classification_columns:
        connection.execute("ALTER TABLE classification DROP COLUMN error")
    queue_columns = {row[1] for row in connection.execute("PRAGMA table_info(queue)")}
    if "status" not in queue_columns:
        connection.execute(
            "ALTER TABLE queue ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'"
        )
    if "error" not in queue_columns:
        connection.execute("ALTER TABLE queue ADD COLUMN error TEXT")
    connection.execute("UPDATE queue SET status = 'pending' WHERE status IS NULL")
    return connection, lock_file


def release_running(db: sqlite3.Connection) -> None:
    """Return jobs left running by a stopped process to the pending queue."""
    db.execute("UPDATE queue SET status = 'pending' WHERE status = 'running'")


def claim_job(db: sqlite3.Connection) -> tuple[str, str] | None:
    """Mark one pending job running and return its session id and prompt."""
    row = db.execute(
        """
        UPDATE queue
        SET status = 'running', error = NULL
        WHERE session_id = (
            SELECT session_id FROM queue
            WHERE status = 'pending'
            ORDER BY session_id
            LIMIT 1
        )
        RETURNING session_id, prompt
        """
    ).fetchone()
    if row is None:
        return None
    return row[0], row[1]


def finish_job(db: sqlite3.Connection, record: dict) -> None:
    """Store a prompt classification and mark its queue row done."""
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            """
            INSERT INTO classification
                (session_id, type, labels, input_tokens, output_tokens, cost, model)
            VALUES (?, 'prompt', ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                type = 'prompt',
                labels = excluded.labels,
                input_tokens = excluded.input_tokens,
                output_tokens = excluded.output_tokens,
                cost = excluded.cost,
                model = excluded.model
            WHERE classification.type = 'error'
            """,
            (
                record["session_id"],
                json.dumps(record["labels"]),
                record.get("input_tokens"),
                record.get("output_tokens"),
                record.get("cost"),
                record.get("model"),
            ),
        )
        db.execute(
            "UPDATE queue SET status = 'done', error = NULL WHERE session_id = ?",
            (record["session_id"],),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def fail_job(db: sqlite3.Connection, session_id: str, error: str) -> None:
    """Mark a queue row error, keep its prompt, and record an error classification."""
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE queue SET status = 'error', error = ? WHERE session_id = ?",
            (error, session_id),
        )
        db.execute(
            """
            INSERT INTO classification
                (session_id, type, labels, input_tokens, output_tokens, cost, model)
            VALUES (?, 'error', NULL, NULL, NULL, NULL, NULL)
            ON CONFLICT(session_id) DO UPDATE SET
                type = 'error',
                labels = NULL,
                input_tokens = NULL,
                output_tokens = NULL,
                cost = NULL,
                model = NULL
            WHERE classification.type = 'error'
            """,
            (session_id,),
        )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
