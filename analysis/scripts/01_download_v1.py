#!/usr/bin/env python3
"""
Step 01 (v1.0): download the AgentLogs core and PR tables, and dump the schema.

We moved from the v0.2 preview to the official 1.0-20261008 release, which adds
pull_requests (additions, deletions, changed_files), pull_request_timelines (PR
comments and reviews), and workflow_runs.

This pulls every table except the 63 GB agent_session_logs, which we fetch later,
column by column, for the RQ2 cost numbers. The download resumes if it is interrupted,
so running it again is safe.
"""
from __future__ import annotations
import json
from pathlib import Path
import duckdb
from huggingface_hub import snapshot_download

REPO_ID = "risenlab/agentlogs"
REVISION = "1.0-20261008"
EXPECTED_VERSION = "1.0-20261008"

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATASET = PROJECT / "data" / "dataset_v1.0"
OUT = PROJECT / "outputs"
OUT_SCHEMA = OUT / "schema_v1.0"
OUT_SCHEMA.mkdir(parents=True, exist_ok=True)

TABLES = ["repositories", "agent_tasks", "agent_sessions", "users",
          "pull_requests", "pull_request_timelines", "workflow_runs"]


def assert_version(path: Path) -> str:
    actual = (path / "VERSION").read_text().strip()
    if actual != EXPECTED_VERSION:
        raise SystemExit(f"VERSION mismatch: got {actual!r}, expected {EXPECTED_VERSION!r}")
    print(f"[version] OK -> {actual}")
    return actual


def main() -> None:
    print(f"[download] {REPO_ID}@{REVISION} (all tables except agent_session_logs) -> {DATASET}")
    snapshot_download(
        repo_id=REPO_ID, repo_type="dataset", revision=REVISION,
        local_dir=str(DATASET),
        allow_patterns=["VERSION", "README.md", "DATA_LICENSE", "docs/**"]
                       + [f"{t}/*" for t in TABLES],
    )
    assert_version(DATASET)

    con = duckdb.connect()
    print("\n=== Row counts (v1.0) ===")
    counts = {}
    for t in TABLES:
        files = DATASET / t
        if not files.exists():
            print(f"  {t:24s} (missing)"); continue
        n = con.sql(f"SELECT count(*) FROM read_parquet('{files}/*.parquet')").fetchone()[0]
        counts[t] = n
        print(f"  {t:24s} {n:>12,}")
    (OUT / "row_counts_v1.0.json").write_text(json.dumps(counts, indent=2))

    print("\n=== Schema dumps -> outputs/schema_v1.0/ ===")
    for t in TABLES:
        files = DATASET / t
        if not files.exists():
            continue
        desc = con.sql(f"DESCRIBE SELECT * FROM read_parquet('{files}/*.parquet')").fetchall()
        lines = [f"{name}\t{typ}" for name, typ, *_ in desc]
        (OUT_SCHEMA / f"{t}.columns.txt").write_text("\n".join(lines) + "\n")
        print(f"  {t}: {len(lines)} columns")

    print("\n[done] step 01 (v1.0) complete.")


if __name__ == "__main__":
    main()
