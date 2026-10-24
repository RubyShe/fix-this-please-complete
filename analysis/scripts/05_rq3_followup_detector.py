#!/usr/bin/env python3
"""
Step 05 (v1.0): the RQ3 follow-up detector.

For every task, decide whether the developer reacted after the agent's output, by either
route:
  Route 1: a later session, i.e. an agent re-run (agent_sessions, more than one session)
  Route 2: a human comment or review on the task's PR (task to
           pull_requests.created_by_tasks to pull_request_timelines, commented or
           reviewed, where the actor is a human and bots are excluded)

reacted = (later sessions >= 1) OR (human PR comments or reviews >= 1)

Output: outputs/rq3_followups_v1.0.parquet (and .csv), one row per task. No GitHub token
and no 63 GB logs: detection comes entirely from the dataset. The bot exclusion here is
the automatic rule (enough for a population-wide pass); the 384-session validation sample
gets borderline commenters checked by hand later.
"""
from __future__ import annotations
from pathlib import Path
import duckdb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
D = PROJECT / "data" / "dataset_v1.0"
OUT = PROJECT / "outputs"; OUT.mkdir(exist_ok=True)

S  = f"read_parquet('{D}/agent_sessions/*.parquet')"
PR = f"read_parquet('{D}/pull_requests/*.parquet')"
TL = f"read_parquet('{D}/pull_request_timelines/*.parquet')"

# same bot heuristic as step 03 (word-boundary so 'abbott' is NOT a bot)
BOTRE = r"(^|[-_.])(bot|robot|ci|cibot|assistant|automation|jenkins|buildkite|circleci|dependabot|renovate|mergify|codecov|sonar|netlify|vercel|deploy|release|svc|service|action|actions)([-_.]|$)"

con = duckdb.connect()

# Road 1: sessions per task
con.execute(f"""
CREATE TEMP TABLE task_sessions AS
SELECT task.id AS task_id, count(*) AS n_sessions, count(*)-1 AS later_sessions
FROM {S} GROUP BY 1;
""")

# human comment/review events, keyed by PR id (bots auto-excluded)
con.execute(f"""
CREATE TEMP TABLE human_pr_events AS
SELECT pull_request.id AS pr_id, count(*) AS n_human
FROM {TL}
WHERE event IN ('commented','reviewed')
  AND actor.type = 'user'
  AND actor.login IS NOT NULL
  AND actor.login NOT ILIKE '%[bot]%'
  AND NOT (regexp_matches(lower(actor.login), '{BOTRE}')
           OR lower(actor.login) LIKE '%bot' OR lower(actor.login) LIKE '%robot')
GROUP BY 1;
""")

# Road 2: task -> its PR(s) -> human events  (a task may have several PRs; sum)
con.execute(f"""
CREATE TEMP TABLE task_comments AS
SELECT ct.id AS task_id, sum(he.n_human) AS n_human_pr_comments
FROM {PR} p, UNNEST(p.created_by_tasks) AS u(ct)
JOIN human_pr_events he ON he.pr_id = p.id
GROUP BY 1;
""")

# Combine
con.execute("""
CREATE TEMP TABLE rq3 AS
SELECT ts.task_id, ts.n_sessions, ts.later_sessions,
       coalesce(tc.n_human_pr_comments, 0) AS n_human_pr_comments,
       (ts.later_sessions >= 1) AS road1_session,
       (coalesce(tc.n_human_pr_comments,0) >= 1) AS road2_comment,
       (ts.later_sessions >= 1 OR coalesce(tc.n_human_pr_comments,0) >= 1) AS reacted
FROM task_sessions ts
LEFT JOIN task_comments tc USING (task_id);
""")

con.execute(f"COPY rq3 TO '{OUT}/rq3_followups_v1.0.parquet' (FORMAT PARQUET)")
con.execute(f"COPY rq3 TO '{OUT}/rq3_followups_v1.0.csv' (HEADER, DELIMITER ',')")

n = con.sql("SELECT count(*) FROM rq3").fetchone()[0]
print(f"[done] {n:,} tasks -> outputs/rq3_followups_v1.0.parquet (+ .csv)\n")

print("=== PREVIEW: did the developer react? (all tasks, auto bot-filter) ===")
print(con.sql("""
SELECT reacted, count(*) AS tasks, round(100.0*count(*)/sum(count(*)) over(),1) AS pct
FROM rq3 GROUP BY 1 ORDER BY reacted DESC""").df().to_string(index=False))

print("\n=== which road did the reaction come from? ===")
print(con.sql("""
SELECT CASE WHEN road1_session AND road2_comment THEN 'both'
            WHEN road1_session THEN 'later session only'
            WHEN road2_comment THEN 'PR comment only'
            ELSE 'no reaction' END AS source,
  count(*) AS tasks, round(100.0*count(*)/sum(count(*)) over(),1) AS pct
FROM rq3 GROUP BY 1 ORDER BY tasks DESC""").df().to_string(index=False))

print("\n=== among tasks that reacted: how many comments/steers typically? ===")
print(con.sql("""
SELECT median(later_sessions) AS med_later_sessions,
       median(n_human_pr_comments) AS med_pr_comments
FROM rq3 WHERE reacted""").df().to_string(index=False))
