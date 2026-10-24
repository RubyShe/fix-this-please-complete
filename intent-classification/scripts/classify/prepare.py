import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import cast

import duckdb
from agentlogs.schema import AgentSession, AgentSessionLogEntry, assert_dataset_version

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from classification.labels import get_direct_classification
from classification.prompts import build_prompt
from classification.state import open_state

dataset = ROOT / "data" / "dataset_1.0-20261008"
assert_dataset_version(dataset)

duck = duckdb.connect()
paths = sorted((dataset / "agent_session_logs").glob("part_*.parquet"))
session_files: dict[str, list[int]] = defaultdict(list)
file_sessions: list[list[str]] = []

print("Indexing logs", flush=True)
for number, path in enumerate(paths):
    name = str(path).replace("'", "''")
    found = duck.execute(f"SELECT DISTINCT session.id FROM read_parquet('{name}')").fetchall()
    ids = [row[0] for row in found]
    file_sessions.append(ids)
    for session_id in ids:
        session_files[session_id].append(number)
    print(f"{path.name} ({number + 1}/{len(paths)})", flush=True)
print(f"Indexed {len(session_files)} sessions", flush=True)

print("Loading sessions", flush=True)
session_path = str(dataset / "agent_sessions" / "*.parquet").replace("'", "''")
cursor = duck.execute(f"SELECT * FROM read_parquet('{session_path}')")
columns = [item[0] for item in cursor.description]
sessions = [cast(AgentSession, dict(zip(columns, row))) for row in cursor.fetchall()]
by_id = {session["id"]: session for session in sessions}
previous_of: dict[str, AgentSession] = {}
by_task: dict[str, list[AgentSession]] = defaultdict(list)
for session in sessions:
    by_task[session["task"]["id"]].append(session)
for group in by_task.values():
    group.sort(key=lambda session: (session["session_index"], session["id"]))
    for index, session in enumerate(group):
        if index:
            previous_of[session["id"]] = group[index - 1]
print(f"Loaded {len(sessions)} sessions", flush=True)

db, _lock = open_state()
classified = {row[0] for row in db.execute("SELECT session_id FROM classification")}
queued = {row[0] for row in db.execute("SELECT session_id FROM queue")}


def insert_rows(classification_rows: list[tuple], queue_rows: list[tuple]) -> None:
    if not classification_rows and not queue_rows:
        return
    db.execute("BEGIN IMMEDIATE")
    try:
        if classification_rows:
            db.executemany(
                """
                INSERT OR IGNORE INTO classification
                    (session_id, type, labels, input_tokens, output_tokens, cost, model)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                classification_rows,
            )
        if queue_rows:
            db.executemany(
                """
                INSERT INTO queue (session_id, prompt, status)
                SELECT ?, ?, 'pending'
                WHERE NOT EXISTS (SELECT 1 FROM queue WHERE session_id = ?)
                  AND NOT EXISTS (SELECT 1 FROM classification WHERE session_id = ?)
                """,
                [(session_id, prompt, session_id, session_id) for session_id, prompt in queue_rows],
            )
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def store_sessions(session_ids: list[str], label: str) -> None:
    if not session_ids:
        print(label, flush=True)
        return
    wanted: dict[int, set[str]] = defaultdict(set)
    for session_id in session_ids:
        session = by_id[session_id]
        if session["log_found"]:
            for number in session_files.get(session_id, ()):
                wanted[number].add(session_id)
        previous = previous_of.get(session_id)
        if previous is not None and previous["log_found"]:
            for number in session_files.get(previous["id"], ()):
                wanted[number].add(previous["id"])
    logs: dict[str, list[AgentSessionLogEntry]] = defaultdict(list)
    for number, ids in wanted.items():
        name = str(paths[number]).replace("'", "''")
        duck.execute("CREATE OR REPLACE TEMP TABLE fetch_ids (id VARCHAR)")
        duck.executemany("INSERT INTO fetch_ids VALUES (?)", [(session_id,) for session_id in ids])
        fetched = duck.execute(
            f"""
            SELECT session, entry_index, data
            FROM read_parquet('{name}')
            WHERE session.id IN (SELECT id FROM fetch_ids)
              AND parsed
            ORDER BY session.id, entry_index
            """
        ).fetchall()
        for session, entry_index, data in fetched:
            logs[session["id"]].append(cast(AgentSessionLogEntry, {
                "session": session,
                "entry_index": entry_index,
                "parsed": True,
                "raw": None,
                "data": data,
            }))
    classification_rows = []
    queue_rows = []
    for session_id in session_ids:
        session = by_id[session_id]
        previous = previous_of.get(session_id)
        own_log = logs.get(session_id) if session["log_found"] else None
        previous_log = None
        if previous is not None and previous["log_found"]:
            previous_log = logs.get(previous["id"])
        prompt = build_prompt(session, own_log, previous, previous_log)
        if prompt is None:
            classification_rows.append((session_id, "missing", None, None, None, None, None))
            classified.add(session_id)
        else:
            queue_rows.append((session_id, prompt))
            queued.add(session_id)
    insert_rows(classification_rows, queue_rows)
    print(
        f"{label}: {len(classification_rows)} classification, {len(queue_rows)} queued",
        flush=True,
    )


direct_rows = []
for session in sessions:
    if session["id"] in classified:
        continue
    labels = get_direct_classification(session)
    if labels is None:
        continue
    direct_rows.append((session["id"], "direct", json.dumps(labels), None, None, None, None))
    classified.add(session["id"])
insert_rows(direct_rows, [])
print(f"Direct {len(direct_rows)}", flush=True)

for number, path in enumerate(paths):
    store_sessions(
        [
            session_id
            for session_id in file_sessions[number]
            if session_id in by_id and session_id not in classified and session_id not in queued
        ],
        f"{path.name} ({number + 1}/{len(paths)})",
    )
store_sessions(
    [
        session["id"]
        for session in sessions
        if session["id"] not in session_files
        and session["id"] not in classified
        and session["id"] not in queued
    ],
    "no log file",
)

classification_count = db.execute("SELECT COUNT(*) FROM classification").fetchone()[0]
queue_count = db.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
print(f"Classification {classification_count}, queue {queue_count}", flush=True)
