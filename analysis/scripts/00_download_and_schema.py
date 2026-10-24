#!/usr/bin/env python3
"""
Superseded. This early script pinned the v0.2 preview revision. The study uses the
official release 1.0-20261008 (schema v1.0), which you download with
scripts/01_download_v1.py. We keep this one only for provenance; it does not produce
the paper's results.
"""
"""
Step 00 - Download core tables and dump the real schema.

Part of the replication package for:
  "Fix This, Please": An Empirical Study of What Developers Ask
  GitHub's Coding Agent to Do  (MSR 2027, Technical Papers track)

What this does (rerunnable, deterministic):
  1. Pins dataset revision v0.2 and asserts it.
  2. Snapshot-downloads only the small core tables (repositories,
     agent_tasks, agent_sessions, users) plus docs/VERSION.
     The 55 GB agent_session_logs config is intentionally NOT downloaded
     here; it is pulled later only for the token-level cost analysis.
  3. Prints and saves real row counts, reconciled against the paper's
     Table I expected values.
  4. Saves the real column list + types of each core table.
  5. Saves key value distributions used to map paper concepts onto
     real columns (entry point, session state, PR state, model).

Portability note: the official `risenlab-agentlogs` package requires
Python >= 3.12. This script therefore uses the package's version check
when available and falls back to an equivalent local check (reading the
shipped VERSION file) so it runs on Python 3.10+ too.
"""

from __future__ import annotations
import json
from pathlib import Path

import duckdb
from huggingface_hub import snapshot_download

REPO_ID = "risenlab/agentlogs"
REVISION = "v0.2"
EXPECTED_VERSION = "0.2"

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATASET = PROJECT / "data" / "dataset"
OUT_SCHEMA = PROJECT / "outputs" / "schema"
OUT_SCHEMA.mkdir(parents=True, exist_ok=True)

CORE_TABLES = ["repositories", "agent_tasks", "agent_sessions", "users"]

# Paper Table I expected record counts (sanity-check targets, NOT ground truth).
PAPER_EXPECTED = {
    "repositories": 1_812_362,
    "agent_tasks": 309_376,
    "agent_sessions": 551_531,
    "agent_session_logs": 64_378_148,
    "users": 34_183,
}


def assert_version(path: Path) -> str:
    """Assert the snapshot is revision v0.2. Prefer the official helper."""
    try:
        from agentlogs.schema import assert_dataset_version  # py>=3.12 only
        assert_dataset_version(path)
        actual = (path / "VERSION").read_text().strip()
        print(f"[version] official assert_dataset_version OK -> {actual}")
        return actual
    except Exception as e:  # ImportError on py<3.12, or assertion error
        actual = (path / "VERSION").read_text().strip().removeprefix("v")
        if actual != EXPECTED_VERSION:
            raise SystemExit(
                f"VERSION mismatch: snapshot is {actual!r}, expected {EXPECTED_VERSION!r}"
            )
        print(f"[version] local check OK -> {actual}  (official helper unavailable: {type(e).__name__})")
        return actual


def main() -> None:
    print(f"[download] snapshot {REPO_ID}@{REVISION} (core tables only) -> {DATASET}")
    snapshot_download(
        repo_id=REPO_ID,
        repo_type="dataset",
        revision=REVISION,
        local_dir=str(DATASET),
        allow_patterns=[
            "VERSION", "README.md", "DATA_LICENSE", "docs/**",
            "repositories/*", "agent_tasks/*", "agent_sessions/*", "users/*",
        ],
    )
    assert_version(DATASET)

    con = duckdb.connect()

    # 1) Row counts, reconciled against the paper.
    print("\n=== Row counts (actual v0.2 vs paper Table I expected) ===")
    counts = {}
    rows = []
    for cfg in CORE_TABLES:
        n = con.sql(
            f"SELECT count(*) FROM read_parquet('{DATASET}/{cfg}/*.parquet')"
        ).fetchone()[0]
        counts[cfg] = n
        exp = PAPER_EXPECTED[cfg]
        flag = "match" if n == exp else f"DIFFERS ({n-exp:+,})"
        rows.append((cfg, n, exp, flag))
        print(f"  {cfg:16s} actual={n:>12,}  paper={exp:>12,}  {flag}")
    # logs not downloaded here; record expected only
    print(f"  {'agent_session_logs':16s} actual=     (not downloaded)  "
          f"paper={PAPER_EXPECTED['agent_session_logs']:>12,}")
    (PROJECT / "outputs" / "tables").mkdir(parents=True, exist_ok=True)
    (PROJECT / "outputs" / "row_counts.json").write_text(
        json.dumps({"actual": counts, "paper_expected": PAPER_EXPECTED}, indent=2)
    )

    # 2) Schema (columns + types) for each core table.
    print("\n=== Schema dumps -> outputs/schema/ ===")
    for cfg in CORE_TABLES:
        desc = con.sql(
            f"DESCRIBE SELECT * FROM read_parquet('{DATASET}/{cfg}/*.parquet')"
        ).fetchall()
        lines = [f"{name}\t{typ}" for name, typ, *_ in desc]
        (OUT_SCHEMA / f"{cfg}.columns.txt").write_text("\n".join(lines) + "\n")
        print(f"  {cfg}: {len(lines)} columns -> outputs/schema/{cfg}.columns.txt")

    # 3) Key value distributions for concept->column mapping.
    S = f"read_parquet('{DATASET}/agent_sessions/*.parquet')"
    dist = {}
    dist["event_type"] = con.sql(
        f"SELECT event.type AS v, count(*) c FROM {S} GROUP BY 1 ORDER BY c DESC"
    ).df().values.tolist()
    dist["session_state"] = con.sql(
        f"SELECT state AS v, count(*) c FROM {S} GROUP BY 1 ORDER BY c DESC"
    ).df().values.tolist()
    dist["pull_request_state"] = con.sql(
        f"SELECT pull_request.state AS v, count(*) c FROM {S} GROUP BY 1 ORDER BY c DESC"
    ).df().values.tolist()
    dist["model_top20"] = con.sql(
        f"SELECT model AS v, count(*) c FROM {S} GROUP BY 1 ORDER BY c DESC LIMIT 20"
    ).df().values.tolist()
    # prompt presence overall
    dist["prompt_presence"] = con.sql(
        f"SELECT CASE WHEN prompt IS NULL THEN 'null' "
        f"WHEN length(trim(prompt))=0 THEN 'empty' ELSE 'has_text' END v, count(*) c "
        f"FROM {S} GROUP BY 1 ORDER BY c DESC"
    ).df().values.tolist()
    (PROJECT / "outputs" / "value_distributions.json").write_text(
        json.dumps(dist, indent=2, default=str)
    )
    print("  value distributions -> outputs/value_distributions.json")
    print(f"    entry-point (event.type) distinct values: {len(dist['event_type'])}")
    print(f"    prompt presence: {dist['prompt_presence']}")

    print("\n[done] step 00 complete.")


if __name__ == "__main__":
    main()
