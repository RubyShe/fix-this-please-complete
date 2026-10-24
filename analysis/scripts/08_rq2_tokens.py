#!/usr/bin/env python3
"""
Step 08 (v1.0): token counts per ask type (the Table IV tokens column).

Token counts live only in agent_session_logs (63 GB), which we never download. Instead we
read just the token columns over the network with DuckDB httpfs, column-projected, which
transfers a tiny fraction of the table (about four minutes, not 63 GB).

Phase 1 (--fetch): stream the per-session input and output tokens from the logs on
Hugging Face into outputs/session_tokens.parquet. Projecting onto
data.usage.{prompt_tokens, completion_tokens} skips the message payloads.

Phase 2 (default): join the session tokens to tasks (agent_sessions), then to ask type
(sample/rq1_task_labels.csv), and report the per-type median input and output tokens.
"""
import argparse, time
from pathlib import Path
import duckdb, pandas as pd
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE=Path(__file__).resolve().parent; PROJECT=HERE.parent
OUT=PROJECT/"outputs"; OUT.mkdir(exist_ok=True)
REV="1.0-20261008"; BASE=f"hf://datasets/risenlab/agentlogs@{REV}/"
SESS_TOK=OUT/"session_tokens.parquet"

def fetch():
    from huggingface_hub import HfApi
    files=[f for f in HfApi().list_repo_files("risenlab/agentlogs",repo_type="dataset",revision=REV)
           if f.startswith("agent_session_logs/") and f.endswith(".parquet")]
    def one(f):
        for a in range(4):
            try:
                c=duckdb.connect(); c.execute("INSTALL httpfs;LOAD httpfs;")
                return c.sql(f"""SELECT session.id sid,
                  sum(coalesce(data.usage.prompt_tokens,0)) tin,
                  sum(coalesce(data.usage.completion_tokens,0)) tout
                  FROM read_parquet('{BASE}{f}') GROUP BY session.id""").df()
            except Exception:
                if a==3: return pd.DataFrame(columns=["sid","tin","tout"])
                time.sleep(3*(a+1))
    parts=[]
    with ThreadPoolExecutor(max_workers=10) as ex:
        for fut in as_completed([ex.submit(one,f) for f in files]): parts.append(fut.result())
    agg=pd.concat(parts,ignore_index=True).groupby("sid",as_index=False).agg(
        tok_in=("tin","sum"),tok_out=("tout","sum"))
    agg.to_parquet(SESS_TOK); print(f"wrote {SESS_TOK.name} ({len(agg):,} sessions)")

def join(dataset,labels):
    c=duckdb.connect()
    S=f"read_parquet('{dataset}/agent_sessions/*.parquet')"; TOK=f"read_parquet('{SESS_TOK}')"
    LAB=f"read_csv_auto('{labels}')"
    c.sql(f"""CREATE TEMP TABLE tt AS SELECT s.task.id tid,
      sum(coalesce(t.tok_in,0)) tin, sum(coalesce(t.tok_out,0)) tout
      FROM {S} s LEFT JOIN {TOK} t ON t.sid=s.id GROUP BY s.task.id""")
    d=c.sql(f"""SELECT l.ask_type atype, count(*) n,
      round(median(tt.tin)) med_in, round(median(tt.tout)) med_out
      FROM tt JOIN {LAB} l ON l.task_id=tt.tid GROUP BY l.ask_type ORDER BY n DESC""").df()
    d.to_csv(OUT/"rq2_tokens_by_type.csv",index=False)
    print(d.to_string(index=False)); print("wrote outputs/rq2_tokens_by_type.csv")

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--fetch",action="store_true",help="phase 1: stream tokens from HF logs (~4 min)")
    ap.add_argument("--dataset",default=str(PROJECT/"data"/"dataset_v1.0"))
    ap.add_argument("--labels",default=str(PROJECT/"sample"/"rq1_task_labels.csv"))
    a=ap.parse_args()
    if a.fetch: fetch()
    assert SESS_TOK.exists(), "session_tokens.parquet missing -- run with --fetch first"
    join(a.dataset,a.labels)
