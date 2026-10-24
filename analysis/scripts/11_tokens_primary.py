#!/usr/bin/env python3
"""
Step 11 (v1.0): make tokens the primary RQ2/RQ3 cost metric, with credits kept as
secondary. This re-runs every statistic that previously used credits, now on output
tokens (what the agent actually generated; input tokens are cache-inflated).

Per-task token aggregates (DuckDB):
  tok_out_total: summed completion tokens over all sessions of the task
  tok_in_total:  summed prompt tokens over all sessions
  tok_out_first: completion tokens of the first session (session_index = 0)
  tok_out_round: summed completion tokens over round sessions (session_index >= 1 and
                 classification type in prompt or direct)

RQ2: per-type median tok_out (with IQR) and tok_in; Kruskal-Wallis across ask types on
tok_out, pairwise Mann-Whitney with Holm, and Cliff's delta.
RQ3: the round share of tok_out (overall and per-task median); Spearman of total tok_out
against the number of rounds, total tok_out against change size, and first-session tok_out
against change.

Outputs: outputs/tokens_by_task.parquet, outputs/tokens_stats.txt,
         outputs/tables/tokens_macros.tex, outputs/tables/rq2_table_outcomes.tex
"""
from pathlib import Path
import numpy as np, pandas as pd, duckdb, statistics, itertools
from scipy import stats

PROJECT=Path(__file__).resolve().parent.parent
OUT=PROJECT/"outputs"; (OUT/"tables").mkdir(parents=True,exist_ok=True)
DATA=PROJECT/"data"/"dataset_v1.0"
SESS=f"read_parquet('{DATA}/agent_sessions/*.parquet')"
CLS=f"read_parquet('{PROJECT/'data'/'session_classifications.parquet'}')"
TOK=f"read_parquet('{OUT/'session_tokens.parquet'}')"
LAB=PROJECT/"sample"/"rq1_task_labels.csv"
MET=OUT/"rq2_task_metrics_v1.0.parquet"
CATS=["Code Authoring","Failure Reporting","Inquiry","Validation","Delegation","Others"]
SH={"Code Authoring":"CA","Failure Reporting":"FR","Inquiry":"IN","Validation":"VA","Delegation":"DE","Others":"OT"}

con=duckdb.connect()
# per-task token aggregates
agg=con.sql(f"""
  WITH st AS (
    SELECT s.id sid, s.task.id tid, s.session_index si,
           coalesce(t.tok_out,0) tout, coalesce(t.tok_in,0) tin,
           cl.type ctype
    FROM {SESS} s
    LEFT JOIN {TOK} t ON t.sid=s.id
    LEFT JOIN {CLS} cl ON cl.session_id=s.id )
  SELECT tid,
         sum(tout) tok_out_total,
         sum(tin)  tok_in_total,
         sum(CASE WHEN si=0 THEN tout ELSE 0 END) tok_out_first,
         sum(CASE WHEN si>=1 AND ctype IN ('prompt','direct') THEN tout ELSE 0 END) tok_out_round,
         sum(CASE WHEN si>=1 AND ctype IN ('prompt','direct') THEN 1 ELSE 0 END) n_round_sess
  FROM st GROUP BY tid
""").df()
agg.to_parquet(OUT/"tokens_by_task.parquet")

lab=pd.read_csv(LAB)[["task_id","ask_type"]]
met=pd.read_parquet(MET)[["task_id","merge_status","lines_changed","developer_rounds","cost_floor"]]
df=agg.merge(lab,left_on="tid",right_on="task_id",how="inner").merge(met,on="task_id",how="left")
print(f"[info] {len(df):,} labelled tasks with token aggregates.")

# share of tasks with at least one developer round, per ask type (over ALL tasks;
# this is Table II's "% with a round" column and must use the full population).
PCTROUND={}
for _c in CATS+["All"]:
    _g = df if _c=="All" else df[df.ask_type==_c]
    PCTROUND[_c]=round(100*(_g.developer_rounds>0).mean())

# PAPER reports token metrics over tasks whose session logs record usage
# (tok_out_total>0); tasks without a usage log are treated as missing, as for
# change size. Compute everything below over these COVERED tasks.
_cov = df.tok_out_total > 0
TOKCOV = round(100*_cov.mean(), 1)
print(f"[info] token coverage: {_cov.sum():,}/{len(df):,} = {TOKCOV}% (metrics computed over these)")
df = df[_cov].copy()

S=[]
def w(x=""): S.append(str(x)); print(x)
def med(s): s=np.asarray(s,float); return float(np.median(s)) if len(s) else float('nan')
def iqr(s): s=np.asarray(s,float); return (np.percentile(s,25),np.percentile(s,75)) if len(s) else (np.nan,np.nan)
def cliffs(a,b):
    a,b=np.asarray(a,float),np.asarray(b,float)
    if not len(a) or not len(b): return float('nan')
    U=stats.mannwhitneyu(a,b,alternative="two-sided").statistic
    return 2.0*U/(len(a)*len(b))-1.0
def holm(ps):
    ps=np.asarray(ps,float); n=len(ps); order=np.argsort(ps); adj=np.empty(n); run=0.0
    for i,idx in enumerate(order): run=max(run,(n-i)*ps[idx]); adj[idx]=min(run,1.0)
    return adj

# ---------- RQ2: per-type output/input tokens ----------
w("=== RQ2 tokens per ask type (median tok_out [IQR]; median tok_in) ===")
rows=[]
for cat in CATS:
    g=df[df.ask_type==cat]
    lo,hi=iqr(g.tok_out_total)
    rows.append(dict(ask_type=cat,n=len(g),med_out=med(g.tok_out_total),out_lo=lo,out_hi=hi,med_in=med(g.tok_in_total)))
lo,hi=iqr(df.tok_out_total)
rows.append(dict(ask_type="All",n=len(df),med_out=med(df.tok_out_total),out_lo=lo,out_hi=hi,med_in=med(df.tok_in_total)))
tbl=pd.DataFrame(rows); tbl.to_csv(OUT/"rq2_tokens_primary.csv",index=False)
w(tbl.to_string(index=False))

w("\n=== RQ2 Kruskal-Wallis on tok_out across ask types ===")
groups=[df[df.ask_type==c].tok_out_total.values for c in CATS]
H,p=stats.kruskal(*groups); w(f"H={H:.1f}, p={p:.3g}")
w("  pair | Holm p | Cliff's delta (|d|>=0.147 small, 0.33 medium, 0.474 large)")
pairs=list(itertools.combinations(CATS,2)); raw=[]
for x,y in pairs:
    a_,b_=df[df.ask_type==x].tok_out_total.values, df[df.ask_type==y].tok_out_total.values
    _,pv=stats.mannwhitneyu(a_,b_,alternative="two-sided"); raw.append((x,y,pv,cliffs(a_,b_)))
adj=holm([r[2] for r in raw])
for (x,y,pv,d),ap in sorted(zip(raw,adj),key=lambda z:-abs(z[0][3])):
    w(f"    {SH[x]} vs {SH[y]}: Holm p={ap:.3g}, d={d:+.2f}")

# ---------- RQ3: round share of output tokens + correlations ----------
w("\n=== RQ3 round share of OUTPUT tokens ===")
wr=df[df.n_round_sess>0]
share_overall=100*wr.tok_out_round.sum()/wr.tok_out_total.sum() if wr.tok_out_total.sum()>0 else float('nan')
per=[100*r/t for r,t in zip(wr.tok_out_round,wr.tok_out_total) if t>0]
w(f"tasks with >=1 round: {len(wr):,}")
w(f"overall round share of tok_out: {share_overall:.1f}%")
w(f"median per-task round share: {statistics.median(per):.1f}%" if per else "n/a")

w("\n=== RQ3 Spearman correlations (OUTPUT tokens) ===")
d2=df.dropna(subset=["lines_changed"])
rho_rounds=df[["tok_out_total","developer_rounds"]].corr(method="spearman").iloc[0,1]
rho_change=d2[["tok_out_total","lines_changed"]].corr(method="spearman").iloc[0,1]
rho_first =d2[["tok_out_first","lines_changed"]].corr(method="spearman").iloc[0,1]
w(f"total tok_out vs #rounds:        rho={rho_rounds:.2f}")
w(f"total tok_out vs change size:    rho={rho_change:.2f}")
w(f"first-session tok_out vs change: rho={rho_first:.2f}")

(OUT/"tokens_stats.txt").write_text("\n".join(S)+"\n")

# ---------- macros ----------
def fout(x): return f"{x/1000:.1f}k"                                   # output: 17.4k
def fin(x):  return f"{x/1e6:.1f}M"                                    # input: always in millions, e.g. 2.8M / 0.4M
mac=["% Generated by scripts/11_tokens_primary.py -- do not edit by hand."]
nm={ "Code Authoring":"CA","Failure Reporting":"FR","Inquiry":"IN","Validation":"VA","Delegation":"DE","Others":"OT","All":"All"}
inAll=None
for r in rows:
    c=nm.get(r["ask_type"],"All")
    mac.append(f"\\newcommand{{\\rqOut{c}}}{{{fout(r['med_out'])}\\xspace}}")
    mac.append(f"\\newcommand{{\\rqIn{c}}}{{{fin(r['med_in'])}\\xspace}}")
    if c=="All": inAll=fin(r['med_in'])
mac.append(f"\\newcommand{{\\rqInMedAll}}{{{inAll}\\xspace}}")
mac.append(f"\\newcommand{{\\rqTokCoverage}}{{{TOKCOV}}}")
for _c in CATS+["All"]:
    _cc={ "Code Authoring":"CA","Failure Reporting":"FR","Inquiry":"IN","Validation":"VA","Delegation":"DE","Others":"OT","All":"All"}[_c]
    mac.append(f"\\newcommand{{\\rqPctRound{_cc}}}{{{PCTROUND[_c]}}}")
mac.append(f"\\newcommand{{\\rqTokKW}}{{{round(H):,}}}".replace(",","{,}"))
mac.append(f"\\newcommand{{\\rqThreeTokShare}}{{{round(share_overall)}}}")
mac.append(f"\\newcommand{{\\rqThreeMedTokShare}}{{{round(statistics.median(per))}}}")
mac.append(f"\\newcommand{{\\rqThreeRhoTokRounds}}{{{rho_rounds:.2f}}}")
mac.append(f"\\newcommand{{\\rqThreeRhoTokChange}}{{{rho_change:.2f}}}")
mac.append(f"\\newcommand{{\\rqThreeRhoTokFirstChange}}{{{rho_first:.2f}}}")
(OUT/"tables"/"tokens_macros.tex").write_text("\n".join(mac)+"\n")
# ---------- RQ2 outcomes table (the paper's Table 2) ----------
# Tokens and %-with-a-round come from here; merge rate and change size come from
# scripts/04 (computed over all/resolved tasks). Input tokens are shown in millions
# for every row, matching the paper's formatting.
import csv as _csv
_mc={}
with open(OUT/"rq2_table_iv.csv") as _f:
    for _r in _csv.DictReader(_f):
        _mc[_r["ask_type"]]=(round(float(_r["merge_rate"])), round(float(_r["change"])))
_tok={r["ask_type"]:r for r in rows}
def _inM(x): return f"{x/1e6:.1f}M"
def _outk(x): return f"{x/1000:.1f}k"
T=["% Generated by scripts/11_tokens_primary.py -- do not edit by hand.",
   "\\begin{table}[t]",
   "\\caption{Per-ask-type outcomes (per-task medians over the \\rqTokCoverage\\% of tasks with usage logs; merge rate over resolved PRs). Output tokens are the cost metric.}",
   "\\label{tab:rq2}","\\centering","\\setlength{\\tabcolsep}{4pt}",
   "\\begin{tabular}{lrrrrr}","\\toprule",
   "Ask type & \\makecell[r]{Input\\\\tokens} & \\makecell[r]{Output\\\\tokens} & \\makecell[r]{Change\\\\size} & \\makecell[r]{Merge\\\\rate} & \\makecell[r]{\\% w/\\\\round} \\\\",
   "\\midrule"]
for _cat in CATS:
    _tr=_tok[_cat]; _mr,_ch=_mc[_cat]
    T.append(f"{_cat} & {_inM(_tr['med_in'])} & {_outk(_tr['med_out'])} & {_ch} & {_mr}\\% & {PCTROUND[_cat]}\\% \\\\")
T.append("\\midrule")
_tr=_tok["All"]; _mr,_ch=_mc["All"]
T.append(f"All & {_inM(_tr['med_in'])} & {_outk(_tr['med_out'])} & {_ch} & {_mr}\\% & {PCTROUND['All']}\\% \\\\")
T+=["\\bottomrule","\\end{tabular}","\\end{table}"]
(OUT/"tables"/"rq2_table_outcomes.tex").write_text("\n".join(T)+"\n")
w("wrote outputs/tables/rq2_table_outcomes.tex (paper RQ2 table)")

w("\nwrote outputs/rq2_tokens_primary.csv, tokens_by_task.parquet, tokens_stats.txt, tables/tokens_macros.tex")
