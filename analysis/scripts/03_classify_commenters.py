#!/usr/bin/env python3
"""
Step 03 (v1.0): label every PR commenter as bot, human, or suspicious.

To count developer comments (RQ2) and reactions (RQ3), we have to leave out bot and CI
accounts. Some bots are not tagged as such (type is user, no [bot] suffix), so we do not
exclude by name alone. Instead:
  obvious bot:   actor.type is bot, or the login ends in [bot]   (excluded automatically)
  suspicious:    not a bot, no [bot], but a bot-like name         (sent for manual review)
  obvious human: everything else                                 (kept automatically)

We only auto-exclude the clear bots; anything in doubt goes to a hand-checked list and is
never dropped silently. The bot-like-name rule is deliberately over-inclusive (it will
catch the surname talbot, say), which is fine precisely because that list is reviewed by
hand rather than dropped.

Outputs:
  outputs/rq3_commenter_classification.csv: all commenters, with class and count
  outputs/rq3_suspicious_commenters.csv: the suspicious ones, with a blank is_bot column to fill
"""
from pathlib import Path
import duckdb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
D = PROJECT / "data" / "dataset_v1.0"
OUT = PROJECT / "outputs"
TL = f"read_parquet('{D}/pull_request_timelines/*.parquet')"

con = duckdb.connect()

# Universe: everyone who authored a comment or a review.
con.execute(f"""
CREATE TEMP TABLE commenters AS
SELECT
  actor.login            AS login,
  any_value(actor.type)  AS actor_type,
  count(*)               AS n_events,
  sum((event='commented')::int) AS n_comments,
  sum((event='reviewed')::int)  AS n_reviews
FROM {TL}
WHERE event IN ('commented','reviewed') AND actor.login IS NOT NULL
GROUP BY 1;
""")

# Bot-like name heuristic (word-boundary so 'idabbott' / 'abbott' do NOT match;
# but 'ydbot', 'maslowbot', 'gh-aw-bot', 'k8s-ci-robot' DO).
BOTRE = r"(^|[-_.])(bot|robot|ci|cibot|assistant|automation|jenkins|buildkite|circleci|dependabot|renovate|mergify|codecov|sonar|netlify|vercel|deploy|release|svc|service|action|actions)([-_.]|$)"
con.execute(f"""
CREATE TEMP TABLE classified AS
SELECT *,
  CASE
    WHEN actor_type='bot' OR login ILIKE '%[bot]%'                      THEN 'OBVIOUS_BOT'
    WHEN regexp_matches(lower(login), '{BOTRE}')
         OR lower(login) LIKE '%bot%' OR lower(login) LIKE '%robot%'      THEN 'SUSPICIOUS'
    ELSE 'OBVIOUS_HUMAN'
  END AS klass
FROM commenters;
""")

print("=== commenter classification (all PR commenters) ===")
print(con.sql("""SELECT klass, count(*) accounts, sum(n_comments) total_comments
                 FROM classified GROUP BY 1 ORDER BY total_comments DESC""").df().to_string(index=False))

# Save full classification + the suspicious review list (with a blank is_bot column).
con.execute(f"""COPY (SELECT login, actor_type, klass, n_comments, n_reviews, n_events
                      FROM classified ORDER BY klass, n_comments DESC)
                TO '{OUT}/rq3_commenter_classification.csv' (HEADER, DELIMITER ',')""")
con.execute(f"""COPY (SELECT login, actor_type, n_comments, n_reviews, '' AS is_bot_FILL_yes_no
                      FROM classified WHERE klass='SUSPICIOUS' ORDER BY n_comments DESC)
                TO '{OUT}/rq3_suspicious_commenters.csv' (HEADER, DELIMITER ',')""")

n_susp = con.sql("SELECT count(*) FROM classified WHERE klass='SUSPICIOUS'").fetchone()[0]
print(f"\n=== SUSPICIOUS list: {n_susp} accounts to hand-check -> outputs/rq3_suspicious_commenters.csv ===")
print(con.sql("""SELECT login, actor_type, n_comments FROM classified
                 WHERE klass='SUSPICIOUS' ORDER BY n_comments DESC LIMIT 40""").df().to_string(index=False))

print("\n=== proof: a few OBVIOUS_HUMAN with 'bot' substring (must be real people, not flagged) ===")
print(con.sql("""SELECT login, n_comments FROM classified
                 WHERE klass='OBVIOUS_HUMAN' AND lower(login) LIKE '%bot%'
                 ORDER BY n_comments DESC LIMIT 10""").df().to_string(index=False))
