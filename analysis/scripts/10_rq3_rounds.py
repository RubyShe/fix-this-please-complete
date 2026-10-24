#!/usr/bin/env python3
"""
Step 10 (v1.0): RQ3, the follow-up rounds after the first ask.

Unit: tasks in the RQ2 population (first session labelled, type not missing or error). A
round is a later session (session_index >= 1) that carries developer content
(classification type in prompt or direct); later sessions marked missing or error are
automatic agent re-runs, not rounds. Round intents use the same 6/14 taxonomy as Table
III, already assigned by the classifier to every session.

Outputs (committed):
  outputs/rq3_rounds_distribution.csv: Table V, round intents against asks, plus the repeated %
  outputs/rq3_rounds_summary.txt: prevalence, cost share, correlations, end states
  outputs/tables/rq3_macros.tex: the LaTeX macros for the prose
  outputs/tables/rq3_tableV.tex: a drop-in Table V (6/14)
Run: python3 scripts/10_rq3_rounds.py (parts A to C; add --timeline for D and E)
"""
from __future__ import annotations
import argparse, csv, json, statistics
from pathlib import Path
from collections import defaultdict, OrderedDict
import duckdb

HERE=Path(__file__).resolve().parent; PROJECT=HERE.parent
DATA=PROJECT/"data"/"dataset_v1.0"; OUT=PROJECT/"outputs"; (OUT/"tables").mkdir(parents=True,exist_ok=True)
SESS=f"read_parquet('{DATA}/agent_sessions/*.parquet')"
CLS=f"read_parquet('{PROJECT/'data'/'session_classifications.parquet'}')"
MET=f"read_parquet('{OUT/'rq2_task_metrics_v1.0.parquet'}')"

ap=argparse.ArgumentParser(); ap.add_argument("--timeline",action="store_true"); args=ap.parse_args()

# label -> (main cat, sub label) ; order as Table III
ROWS=[("code_creation","1. Code Authoring","1.1 New Implementation"),
 ("code_change","1. Code Authoring","1.2 Iterative Modification"),
 ("code_unspecified","1. Code Authoring","1.3 Unspecified Authoring"),
 ("failure_log","2. Failure Reporting","2.1 Log Paste"),
 ("failure_symptom","2. Failure Reporting","2.2 Symptom Description"),
 ("failure_unspecified","2. Failure Reporting","2.3 Unspecified Failure"),
 ("question_plan","3. Inquiry","3.1 Planning \\& Consultation"),
 ("question_project","3. Inquiry","3.2 Project Comprehension"),
 ("question_general","3. Inquiry","3.3 General Knowledge Query"),
 ("review_code","4. Validation","4.1 Code Review"),
 ("review_runtime","4. Validation","4.2 Runtime Inspection"),
 ("documentation","5. Delegation","5.1 Documentation"),
 ("dev_operation","5. Delegation","5.2 Toolchain Operation"),
 ("other","6. Others","6. Others")]
LAB2CAT={l:c for l,c,_ in ROWS}; LAB2SUB={l:s for l,_,s in ROWS}
CATS=["1. Code Authoring","2. Failure Reporting","3. Inquiry","4. Validation","5. Delegation","6. Others"]
CORRECTIVE=lambda lab: (LAB2CAT.get(lab)=="2. Failure Reporting") or (lab=="code_change")

con=duckdb.connect()
# version check
assert "1.0-20261008" in (DATA/"VERSION").read_text()

# ---- population tasks (first session labelled) + ask type per task ----
con.execute(f"""CREATE TEMP TABLE firsts AS
 SELECT s.task.id AS tid, cl.labels[1] AS ask_lab
 FROM {SESS} s JOIN {CLS} cl ON cl.session_id=s.id
 WHERE s.session_index=0 AND cl.type NOT IN ('missing','error')
   AND cl.labels IS NOT NULL AND len(cl.labels)>0;""")
NTASK=con.sql("SELECT count(*) FROM firsts").fetchone()[0]

# ---- round sessions (later sessions with developer content) ----
con.execute(f"""CREATE TEMP TABLE rounds AS
 SELECT s.task.id AS tid, s.id AS sid, s.session_index AS si,
        cl.labels[1] AS lab, coalesce(s.premium_requests,0) AS cred
 FROM {SESS} s JOIN {CLS} cl ON cl.session_id=s.id
 WHERE s.session_index>=1 AND cl.type IN ('prompt','direct')
   AND cl.labels IS NOT NULL AND len(cl.labels)>0
   AND s.task.id IN (SELECT tid FROM firsts);""")
NROUND=con.sql("SELECT count(*) FROM rounds").fetchone()[0]

# ---- prevalence ----
rc=con.sql("SELECT tid, count(*) r FROM rounds GROUP BY tid").df()
tasks_with=len(rc)
med_rounds=int(statistics.median(rc.r)) if len(rc) else 0
pct_with=100*tasks_with/NTASK
# full distribution of rounds-per-task (incl zero): median over all tasks
all_counts=[0]*(NTASK-tasks_with)+list(rc.r)
med_rounds_all=int(statistics.median(all_counts))

# ---- Table V: round intent distribution + Asks% + Repeated% ----
rd=con.sql("SELECT tid, si, lab FROM rounds ORDER BY tid, si").df()
round_lab_counts=defaultdict(int)
# repeated (corrective recurrence): per round, any LATER round in same task is corrective
rep_num=defaultdict(int); rep_den=defaultdict(int); rep_total_num=0
by_task=defaultdict(list)
for tid,si,lab in rd.itertuples(index=False):
    by_task[tid].append((si,lab))
for tid,seq in by_task.items():
    seq.sort()
    labs=[l for _,l in seq]
    for i,lab in enumerate(labs):
        round_lab_counts[lab]+=1
        later_corr=any(CORRECTIVE(labs[j]) for j in range(i+1,len(labs)))
        rep_den[lab]+=1
        if later_corr: rep_num[lab]+=1; rep_total_num+=1
# Asks% population from rq1 distribution
ask_pct={}
for row in csv.DictReader(open(OUT/"rq1_asktypes_distribution.csv")):
    if row["label"]: ask_pct[row["label"]]=float(row["population_pct"])

def pct(a,b): return round(100*a/b,1) if b else 0.0
# rollups
cat_round=defaultdict(int); cat_askpct=defaultdict(float); cat_repnum=defaultdict(int); cat_repden=defaultdict(int)
for lab,cat,_ in ROWS:
    cat_round[cat]+=round_lab_counts.get(lab,0)
    cat_askpct[cat]+=ask_pct.get(lab,0.0)
    cat_repnum[cat]+=rep_num.get(lab,0); cat_repden[cat]+=rep_den.get(lab,0)

# ---- cost: round-credit share ----
# total task credits (floor) and round credits (floor) over tasks-with-rounds
tc=con.sql("""
 WITH tot AS (SELECT s.task.id tid, sum(coalesce(s.premium_requests,0)) task_cred
              FROM read_parquet('{S}') s WHERE s.task.id IN (SELECT tid FROM firsts) GROUP BY 1),
      rnd AS (SELECT tid, sum(cred) round_cred FROM rounds GROUP BY 1)
 SELECT t.tid, t.task_cred, coalesce(r.round_cred,0) round_cred
 FROM tot t JOIN rnd r ON r.tid=t.tid
""".replace("{S}",f"{DATA}/agent_sessions/*.parquet")).df()
share_overall=100*tc.round_cred.sum()/tc.task_cred.sum() if tc.task_cred.sum()>0 else 0
per_share=[100*rcred/tcred for rcred,tcred in zip(tc.round_cred,tc.task_cred) if tcred>0]
med_share=round(statistics.median(per_share),1) if per_share else 0

# ---- correlations (Spearman via pandas, handles ties) ----
cdf=con.sql(f"""
 WITH firstcred AS (SELECT task.id tid, coalesce(premium_requests,0) fc FROM {SESS} WHERE session_index=0)
 SELECT m.cost_floor, m.lines_changed, m.developer_rounds, f.fc
 FROM {MET} m JOIN firstcred f ON f.tid=m.task_id
 WHERE m.task_id IN (SELECT tid FROM firsts)
""").df()
class _C: pass
corr=_C()
corr.cost_vs_change=cdf[["cost_floor","lines_changed"]].corr(method="spearman").iloc[0,1]
corr.cost_vs_rounds=cdf[["cost_floor","developer_rounds"]].corr(method="spearman").iloc[0,1]
corr.firstcost_vs_change=cdf[["fc","lines_changed"]].corr(method="spearman").iloc[0,1]
corr.n_change=int(cdf["lines_changed"].notna().sum())

# ---------- write distribution CSV + table + macros ----------
dist_csv=OUT/"rq3_rounds_distribution.csv"
with open(dist_csv,"w",newline="") as fh:
    w=csv.writer(fh); w.writerow(["main_category","sub_label","label","round_n","round_pct","ask_pct","repeated_pct"])
    for lab,cat,sub in ROWS:
        w.writerow([cat,sub,lab,round_lab_counts.get(lab,0),pct(round_lab_counts.get(lab,0),NROUND),
                    ask_pct.get(lab,0.0),pct(rep_num.get(lab,0),rep_den.get(lab,0))])
    w.writerow(["TOTAL","","",NROUND,100.0,100.0,pct(rep_total_num,NROUND)])

summary=[]
summary.append(f"RQ3 population tasks: {NTASK:,}")
summary.append(f"round sessions (developer rounds): {NROUND:,}")
summary.append(f"tasks with >=1 round: {tasks_with:,} ({pct_with:.1f}%)")
summary.append(f"median rounds among tasks-with-rounds: {med_rounds} ; median over all tasks: {med_rounds_all}")
summary.append(f"round-credit share overall: {share_overall:.1f}% ; median per-task share: {med_share}%")
summary.append(f"Spearman cost_floor vs change: {corr.cost_vs_change:.3f} ; vs rounds: {corr.cost_vs_rounds:.3f} ; first-session cost vs change: {corr.firstcost_vs_change:.3f} (n_change={int(corr.n_change):,})")
summary.append("")
summary.append(f"{'intent':34s}{'round_n':>9}{'round%':>8}{'ask%':>7}{'rep%':>7}")
for cat in CATS:
    summary.append(f"{cat:34s}{cat_round[cat]:>9,}{pct(cat_round[cat],NROUND):>8}{round(cat_askpct[cat],1):>7}{pct(cat_repnum[cat],cat_repden[cat]):>7}")
    for lab,c,sub in ROWS:
        if c!=cat or cat.startswith('6'): continue
        summary.append(f"  {sub:32s}{round_lab_counts.get(lab,0):>9,}{pct(round_lab_counts.get(lab,0),NROUND):>8}{ask_pct.get(lab,0):>7}{pct(rep_num.get(lab,0),rep_den.get(lab,0)):>7}")
(OUT/"rq3_rounds_summary.txt").write_text("\n".join(summary)+"\n")
print("\n".join(summary))

# ---- per-ask-type: which ask types attract most rounds, and round-intent co-occurrence ----
asklab=con.sql("SELECT tid, ask_lab FROM firsts").df().set_index("tid")["ask_lab"].to_dict()
cooc=defaultdict(lambda:defaultdict(int))  # ask main cat -> round main cat -> count
for tid,si,lab in rd.itertuples(index=False):
    a=asklab.get(tid); 
    if a is None: continue
    cooc[LAB2CAT.get(a)][LAB2CAT.get(lab)]+=1
(OUT/"rq3_cooccurrence.json").write_text(json.dumps({k:dict(v) for k,v in cooc.items()},indent=1))

# ---- macros ----
def m(n,v): return f"\\newcommand{{\\{n}}}{{{v}}}"
short={"1. Code Authoring":"CA","2. Failure Reporting":"FR","3. Inquiry":"IN","4. Validation":"VA","5. Delegation":"DE","6. Others":"OT"}
mac=["% Generated by scripts/10_rq3_rounds.py -- do not edit by hand.",
 m("rqThreeTasksWith",f"{tasks_with:,}".replace(",","{,}")),
 m("rqThreePctWith",f"{pct_with:.1f}"),
 m("rqThreeMedRounds",med_rounds),
 m("rqThreeNRounds",f"{NROUND:,}".replace(",","{,}")),
 m("rqThreeCreditShare",f"{share_overall:.0f}"),
 m("rqThreeMedShare",f"{med_share:.0f}"),
 m("rqThreeRhoRounds",f"{corr.cost_vs_rounds:.2f}"),
 m("rqThreeRhoChange",f"{corr.cost_vs_change:.2f}"),
 m("rqThreeRhoFirstChange",f"{corr.firstcost_vs_change:.2f}"),
 m("rqThreeRepTotal",f"{pct(rep_total_num,NROUND):.0f}")]
for cat in CATS:
    mac.append(m(f"rqThreeRound{short[cat]}",f"{pct(cat_round[cat],NROUND):.1f}"))
    mac.append(m(f"rqThreeRep{short[cat]}",f"{pct(cat_repnum[cat],cat_repden[cat]):.0f}"))
(OUT/"tables"/"rq3_macros.tex").write_text("\n".join(mac)+"\n")
print("\nwrote",dist_csv,"and rq3_macros.tex")

# ================= PART D: end states + takeover (timeline) =================
if args.timeline:
    TL=f"read_parquet('{DATA}/pull_request_timelines/*.parquet')"
    # task -> PR id + agent last activity
    con.execute(f"""CREATE TEMP TABLE taskpr AS
      SELECT s.task.id tid,
             max(s.pull_request_artifact.id) pr_id,
             max(s.completed_at) agent_last
      FROM {SESS} s WHERE s.task.id IN (SELECT tid FROM firsts)
      GROUP BY 1;""")
    # human commits/force-pushes on those PRs, with time
    con.execute(f"""CREATE TEMP TABLE humanpush AS
      SELECT t.pull_request.id pr_id, t.created_at ts
      FROM {TL} t
      WHERE t.event IN ('committed','head_ref_force_pushed')
        AND t.actor.type <> 'bot'
        AND coalesce(t.actor.login,'') NOT LIKE '%[bot]'
        AND t.pull_request.id IN (SELECT pr_id FROM taskpr WHERE pr_id IS NOT NULL);""")
    # takeover = a human push on the task's PR strictly after the agent's last session
    con.execute("""CREATE TEMP TABLE takeover AS
      SELECT tp.tid,
             max(CASE WHEN h.ts > tp.agent_last THEN 1 ELSE 0 END) AS taken
      FROM taskpr tp LEFT JOIN humanpush h ON h.pr_id = tp.pr_id
      WHERE tp.pr_id IS NOT NULL
      GROUP BY tp.tid;""")
    # join end state + rounds
    endf=con.sql(f"""
      SELECT m.task_id tid, m.merge_status ms, m.has_pr, m.developer_rounds dr,
             coalesce(tk.taken,0) taken
      FROM {MET} m LEFT JOIN takeover tk ON tk.tid=m.task_id
      WHERE m.task_id IN (SELECT tid FROM firsts)
    """).df()
    import pandas as pd
    def P(a,b): return round(100*a/b,1) if b else 0.0
    with_rounds=endf[endf.dr>=1]
    allpr=endf[endf.has_pr==True]
    lines=[]
    lines.append(f"tasks with a PR: {len(allpr):,}")
    lines.append(f"takeover (human pushed after agent's last session), among tasks with a PR: "
                 f"{int(allpr.taken.sum()):,} ({P(allpr.taken.sum(),len(allpr))}%)")
    lines.append(f"takeover among tasks WITH >=1 round: {int(with_rounds.taken.sum()):,} "
                 f"({P(with_rounds.taken.sum(),len(with_rounds))}%)  (n={len(with_rounds):,})")
    # end states among tasks with rounds
    for st in ["merged","closed_no_merge","open","no_pr"]:
        n=int((with_rounds.ms==st).sum()); lines.append(f"  with-rounds end state {st}: {n:,} ({P(n,len(with_rounds))}%)")
    # end states by number of rounds bucket
    lines.append("end states by #rounds (merged% / taken% / closed% / open%):")
    def bucket(d): return "0" if d==0 else ("1" if d==1 else ("2" if d==2 else "3+"))
    endf["b"]=endf.dr.apply(bucket)
    for b in ["0","1","2","3+"]:
        g=endf[endf.b==b]; n=len(g)
        if not n: continue
        mp=P((g.ms=='merged').sum(),n); tp=P(g.taken.sum(),n)
        cp=P((g.ms=='closed_no_merge').sum(),n); op=P((g.ms=='open').sum(),n)
        lines.append(f"  {b:>3} rounds (n={n:,}): merged {mp}% / taken {tp}% / closed {cp}% / open {op}%")
    txt="\n".join(lines)
    (OUT/"rq3_endstates.txt").write_text(txt+"\n"); print(txt)
    # macros
    def m(n,v): return f"\\newcommand{{\\{n}}}{{{v}}}"
    tk_wr=P(with_rounds.taken.sum(),len(with_rounds))
    merged_wr=P((with_rounds.ms=='merged').sum(),len(with_rounds))
    emac=["% end-state macros (scripts/10_rq3_rounds.py --timeline)",
          m("rqThreeTakeover",f"{tk_wr:.0f}"),
          m("rqThreeMergedWR",f"{merged_wr:.0f}"),
          m("rqThreeTakeoverAll",f"{P(allpr.taken.sum(),len(allpr)):.0f}")]
    (OUT/"tables"/"rq3_endstate_macros.tex").write_text("\n".join(emac)+"\n")
    print("wrote rq3_endstates.txt + rq3_endstate_macros.tex")

# ================= Table V (.tex), 6/14, drop-in =================
def _f1(x): return f"{x:.1f}"
Lt=["% Generated by scripts/10_rq3_rounds.py -- do not edit by hand.",
 "\\begin{table}[t]",
 "\\caption{Intents of follow-up prompts (rounds), classified with the taxonomy of \\tab{tab:rq1}. "
 "\\# and \\% are the primary label of each round; main-category rows are subtotals. Asks gives the "
 "same label's share among session-initiating asks (\\tab{tab:rq1}). Repeated is the share of rounds "
 "with that primary label whose task has a later corrective round (a Failure Reporting or Iterative "
 "Modification round), i.e., the concern did not settle.}",
 "\\label{tab:rq3}","\\centering","\\footnotesize","\\setlength{\\tabcolsep}{4pt}",
 "\\begin{tabular}{lrrrr}","\\toprule",
 " & \\multicolumn{2}{c}{Rounds} & Asks & Repeated \\\\",
 f" & \\multicolumn{{2}}{{c}}{{$n$ = {NROUND:,}}} & \\% & \\% \\\\".replace(",","{,}"),
 "\\cmidrule(lr){2-3}","Intent (primary label) & \\# & \\% & & \\\\","\\midrule"]
def comma(n): return f"{n:,}".replace(",","{,}")
for cat in CATS:
    rn=cat_round[cat]
    Lt.append(f"\\textbf{{{cat}}} & {comma(rn)} & {_f1(pct(rn,NROUND))} & {_f1(round(cat_askpct[cat],1))} & {pct(cat_repnum[cat],cat_repden[cat]):.0f} \\\\")
    if cat.startswith("6"): continue
    for lab,c,sub in ROWS:
        if c!=cat: continue
        n=round_lab_counts.get(lab,0)
        Lt.append(f"\\quad {sub} & {comma(n)} & {_f1(pct(n,NROUND))} & {_f1(ask_pct.get(lab,0))} & {pct(rep_num.get(lab,0),rep_den.get(lab,0)):.0f} \\\\")
    Lt.append("\\midrule")
Lt.append(f"Total & {comma(NROUND)} & 100.0 & 100.0 & {pct(rep_total_num,NROUND):.0f} \\\\")
Lt+=["\\bottomrule","\\end{tabular}","\\end{table}"]
(OUT/"tables"/"rq3_tableV.tex").write_text("\n".join(Lt)+"\n")
print("wrote rq3_tableV.tex ; overall repeat% =", round(pct(rep_total_num,NROUND),1))
