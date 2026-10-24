#!/usr/bin/env python3
"""
Step 09 (v1.0): the RQ1 sample-characterization numbers the reporting block needs:
  (a) the share of asks that reference a repository artifact (file, issue, PR, error, or
      code), and
  (b) the median prompt length per ask type.

Both come without the 63 GB agent_session_logs, from two local sources.

  agent_sessions.prompt: the developer-typed, free-text ask. It is present for the web
  interface, external tools, and some PR-comment entry points, and NULL for issue
  assignment and review request (there the ask is the linked issue or PR, whose body
  lives only in the logs). We use it for prompt length and for the lexical artifact
  signals (a named file, a pasted error, a code fence, an issue number, a URL).

  event.type, mapped to an entry-point bucket (via
  _working/entrypoint_mapping_draft.json): we use it for structural artifact anchoring.
  An issue assignment or a PR comment or review is, by construction, a reference to a
  repository artifact (the issue or the PR), even when no free text was typed.

So: artifact_reference(ask) is true when the entry point is an issue assignment or a PR
comment, or when the free text names a file, error, code, issue number, or URL.

Length is reported only over asks that carry developer-typed text (word count), per
category. Issue- and PR-anchored asks have no typed prompt and are left out of the length
column (stated as a scope note, not imputed).

Run from the replication-package root:
    python3 scripts/09_rq1_prompt_characterization.py
Outputs:
    outputs/rq1_prompt_characterization.csv
    outputs/tables/rq1_charstics_macros.tex
"""
from __future__ import annotations
import json, csv, statistics, re
from pathlib import Path
import duckdb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA = PROJECT / "data" / "dataset_v1.0"
OUT = PROJECT / "outputs"; (OUT / "tables").mkdir(parents=True, exist_ok=True)
SESS = f"read_parquet('{DATA}/agent_sessions/*.parquet')"
CLS  = f"read_parquet('{PROJECT / 'data' / 'session_classifications.parquet'}')"

# label -> main category (same 14->6 rollup as script 06)
LAB2CAT = {
 "code_creation":"Code Authoring","code_change":"Code Authoring","code_unspecified":"Code Authoring",
 "failure_log":"Failure Reporting","failure_symptom":"Failure Reporting","failure_unspecified":"Failure Reporting",
 "question_plan":"Inquiry","question_project":"Inquiry","question_general":"Inquiry",
 "review_code":"Validation","review_runtime":"Validation",
 "documentation":"Delegation","dev_operation":"Delegation",
 "other":"Others",
}
CATS = ["Code Authoring","Failure Reporting","Inquiry","Validation","Delegation","Others"]

# raw event.type -> entry bucket
emap = {e["raw"]: e["bucket"] for e in json.loads((PROJECT/"_working"/"entrypoint_mapping_draft.json").read_text())}
ANCHOR = {"issue_assignment","pr_comment"}  # structurally references a repo artifact

# lexical artifact signals in developer-typed text
RE_FILE = re.compile(r'[A-Za-z0-9_./-]+\.(py|js|ts|tsx|jsx|java|go|rb|rs|cpp|cc|c|h|hpp|cs|php|md|rst|json|yaml|yml|sh|sql|html|css|xml|toml|cfg|ini|txt|gradle|lock)\b', re.I)
RE_ERR  = re.compile(r'(?i)(error|exception|traceback|stack ?trace|failed|failing|assertion|segfault|panic:)')
RE_CODE = re.compile(r'```')
RE_ISS  = re.compile(r'(?<![\w])#\d+\b')
RE_URL  = re.compile(r'https?://')

con = duckdb.connect()
rows = con.execute(f"""
  SELECT cl.labels[1] AS prim, s.event.type AS et, s.prompt AS prompt
  FROM {SESS} s JOIN {CLS} cl ON cl.session_id = s.id
  WHERE s.session_index = 0
    AND cl.type NOT IN ('missing','error')
    AND cl.labels IS NOT NULL AND len(cl.labels) > 0
""").fetchall()

per = {c: {"n":0,"anchor":0,"lex":0,"artifact":0,"lens":[],
           "file":0,"err":0,"code":0,"iss":0,"url":0,"typed":0} for c in CATS}
tot = {k:(0 if k!="lens" else []) for k in per["Others"]}

for prim, et, prompt in rows:
    cat = LAB2CAT.get(prim)
    if cat is None:
        continue
    d = per[cat]
    d["n"] += 1; tot["n"] += 1
    bucket = emap.get(et)
    anchored = bucket in ANCHOR
    txt = (prompt or "").strip()
    has_file = bool(txt) and bool(RE_FILE.search(txt))
    has_err  = bool(txt) and bool(RE_ERR.search(txt))
    has_code = bool(txt) and bool(RE_CODE.search(txt))
    has_iss  = bool(txt) and bool(RE_ISS.search(txt))
    has_url  = bool(txt) and bool(RE_URL.search(txt))
    lexical  = has_file or has_err or has_code or has_iss or has_url
    artifact = anchored or lexical
    if anchored: d["anchor"]+=1; tot["anchor"]+=1
    if lexical:  d["lex"]+=1;    tot["lex"]+=1
    if artifact: d["artifact"]+=1; tot["artifact"]+=1
    for key,flag in (("file",has_file),("err",has_err),("code",has_code),("iss",has_iss),("url",has_url)):
        if flag: d[key]+=1; tot[key]+=1
    if txt:
        wl = len(txt.split())
        d["typed"]+=1; tot["typed"]+=1
        d["lens"].append(wl); tot["lens"].append(wl)

def pct(a,b): return round(100*a/b,1) if b else 0.0
def med(xs): return int(statistics.median(xs)) if xs else None

# ---- CSV ----
csv_path = OUT / "rq1_prompt_characterization.csv"
with open(csv_path,"w",newline="") as f:
    w=csv.writer(f)
    w.writerow(["category","n","artifact_ref_pct","anchored_pct","lexical_pct",
                "file_pct","error_pct","code_pct","issue_pct","url_pct",
                "n_typed","median_prompt_words","p25_words","p75_words"])
    for c in CATS+["ALL"]:
        d = per.get(c) or tot
        if c=="ALL": d=tot
        lens=sorted(d["lens"])
        q=lambda p: int(statistics.quantiles(lens,n=4)[p]) if len(lens)>=4 else (lens[0] if lens else None)
        w.writerow([c,d["n"],pct(d["artifact"],d["n"]),pct(d["anchor"],d["n"]),pct(d["lex"],d["n"]),
                    pct(d["file"],d["n"]),pct(d["err"],d["n"]),pct(d["code"],d["n"]),pct(d["iss"],d["n"]),pct(d["url"],d["n"]),
                    d["typed"], med(d["lens"]), q(0), q(2)])

# ---- macros ----
def m(name,val): return f"\\newcommand{{\\{name}}}{{{val}\\xspace}}"
tl=sorted(tot["lens"])
macros=[
 "% Generated by scripts/09_rq1_prompt_characterization.py -- do not edit by hand.",
 m("rqArtifactPct", pct(tot["artifact"],tot["n"])),
 m("rqAnchorPct",   pct(tot["anchor"],tot["n"])),
 m("rqLexicalPct",  pct(tot["lex"],tot["n"])),
 m("rqTypedPct",    pct(tot["typed"],tot["n"])),
 m("rqPromptMedWords", med(tot["lens"])),
 m("rqPromptIQRlo", int(statistics.quantiles(tl,n=4)[0])),
 m("rqPromptIQRhi", int(statistics.quantiles(tl,n=4)[2])),
]
# per-category median words (typed asks)
short={"Code Authoring":"CA","Failure Reporting":"FR","Inquiry":"IN","Validation":"VA","Delegation":"DE","Others":"OT"}
for c in CATS:
    macros.append(m(f"rqArtifact{short[c]}", pct(per[c]['artifact'],per[c]['n'])))
    macros.append(m(f"rqMedWords{short[c]}", med(per[c]['lens'])))
(OUT/"tables"/"rq1_charstics_macros.tex").write_text("\n".join(macros)+"\n")

# ---- console ----
print(f"labelled first-session asks: {tot['n']:,}")
print(f"typed (free-text) asks: {tot['typed']:,}  ({pct(tot['typed'],tot['n'])}%)")
print(f"ARTIFACT-REFERENCE share: {pct(tot['artifact'],tot['n'])}%  "
      f"(structural anchor {pct(tot['anchor'],tot['n'])}% + lexical {pct(tot['lex'],tot['n'])}%)")
print(f"median prompt length (typed asks): {med(tot['lens'])} words  "
      f"[IQR {int(statistics.quantiles(tl,n=4)[0])}-{int(statistics.quantiles(tl,n=4)[2])}]")
print(f"{'category':18s} {'n':>7} {'artifact%':>9} {'anchor%':>8} {'lex%':>6} {'typed':>7} {'medWords':>8}")
for c in CATS:
    d=per[c]
    print(f"{c:18s} {d['n']:>7,} {pct(d['artifact'],d['n']):>9} {pct(d['anchor'],d['n']):>8} "
          f"{pct(d['lex'],d['n']):>6} {d['typed']:>7,} {str(med(d['lens'])):>8}")
print("wrote:", csv_path)
print("wrote:", OUT/"tables"/"rq1_charstics_macros.tex")
