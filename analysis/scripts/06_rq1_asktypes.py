#!/usr/bin/env python3
"""
Step 06 (v1.0): the RQ1 ask-type distribution (manual sample and classifier population).

The RQ1 unit is the session-initiating ask, that is, the first session of each task.
The taxonomy is the adapted Tang et al. codebook: 6 main categories, 14 labels.

Two columns, matching Table III in the paper.

  Population (classifier)
    Source: the published AgentLogs intent classification
            (session_classifications.parquet, GPT-6 Luna, revision 1.0-20261008).
    Selection: first sessions (session_index = 0), minus empty or error ones
               (type in missing or error, labels NULL).
    This leaves 324,695 labelled asks.

  Sample (manual)
    Source: the team's manual annotation of the codebook-validation sample
            (data/validation/iteration_4/annotations.json, 384 sessions, seed 123).
    A caveat, for the paper's method text rather than a bug: this 384 is a mix of
    first-session asks and later-session rounds; it excludes direct (review-request)
    events by design; and it was drawn from the v0.2 release (378 of 384 exist in v1.0,
    190 of them as first sessions). It is best read as a validation of the classifier
    (the two distributions agree on the big categories), not as a standalone RQ1 sample.
    We keep both columns for now; the framing is a team decision.

The primary label is the first label (both the classifier and the human coders order them
by dominance). Percentages are of each column's own labelled total.

Outputs (committed to the package):
  outputs/rq1_asktypes_distribution.csv: both columns per label, plus the IDE-chat %
  outputs/tables/rq1_asktypes.md: the same, human-readable
  outputs/tables/rq1_table3.tex: a drop-in Table III with both columns filled
"""
from __future__ import annotations
import argparse, json, csv
from pathlib import Path
from collections import OrderedDict
import duckdb

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parent
DATA = PROJECT / "data" / "dataset_v1.0"
OUT = PROJECT / "outputs"; (OUT / "tables").mkdir(parents=True, exist_ok=True)

ap = argparse.ArgumentParser()
ap.add_argument("--classifications", default=str(PROJECT / "data" / "session_classifications.parquet"))
ap.add_argument("--dataset", default=str(DATA))
ap.add_argument("--manual", default=str(PROJECT / "data" / "validation" / "iteration_4" / "annotations.json"))
ap.add_argument("--sample", default=str(PROJECT / "data" / "validation" / "sample" / "sample.json"))
args = ap.parse_args()

SESS = f"read_parquet('{args.dataset}/agent_sessions/*.parquet')"
CLS = f"read_parquet('{args.classifications}')"

# ---- taxonomy: code -> (label, main, sub, definition, IDE-chat %) ----
# IDE-chat % are Tang et al.'s published shares, kept ONLY for labels we retain
# unchanged; "--" marks labels we redefined/added. Category IDE subtotals are
# "--" where the category composition differs from Tang's.
ROWS = [
 ("1.1","code_creation","1. Code Authoring","1.1 New Implementation",
  "Add functionality that does not yet exist.","5.9"),
 ("1.2","code_change","1. Code Authoring","1.2 Iterative Modification",
  "Change, extend, or constrain existing or in-progress code.","24.8"),
 ("1.3","code_unspecified","1. Code Authoring","1.3 Unspecified Authoring",
  "Write or change code when new-vs-change is unclear from context.","--"),
 ("2.1","failure_log","2. Failure Reporting","2.1 Log Paste",
  "Hand over raw machine output, e.g., stack traces or build logs.","8.8"),
 ("2.2","failure_symptom","2. Failure Reporting","2.2 Symptom Description",
  "Explain a malfunction in prose rather than through logs.","14.8"),
 ("2.3","failure_unspecified","2. Failure Reporting","2.3 Unspecified Failure",
  "Report a failure (``fix it'', ``still broken'') with no log or symptom detail.","--"),
 ("3.1","question_plan","3. Inquiry","3.1 Planning \\& Consultation",
  "Ask how to proceed or which design option to take.","7.8"),
 ("3.2","question_project","3. Inquiry","3.2 Project Comprehension",
  "Ask how the existing code or project currently works.","8.2"),
 ("3.3","question_general","3. Inquiry","3.3 General Knowledge Query",
  "Ask a technical question independent of this project.","3.6"),
 ("4.1","review_code","4. Validation","4.1 Code Review",
  "Examine code for correctness or quality without running it.","2.7"),
 ("4.2","review_runtime","4. Validation","4.2 Runtime Inspection",
  "Check a run, test output, or terminal.","1.3"),
 ("5.1","documentation","5. Delegation","5.1 Documentation",
  "Write artifacts such as docs, comments, or progress logs.","6.9"),
 ("5.2","dev_operation","5. Delegation","5.2 Toolchain Operation",
  "Run, build, commit, deploy, or operate the toolchain.","10.5"),
 ("6.1","other","6. Others","6. Others",
  "Empty, off-topic, or a bare acknowledgement with no recoverable intent.","--"),
]
CAT_DEF = {
 "1. Code Authoring":("The ask wants code written, changed, or tuned.","--"),
 "2. Failure Reporting":("The ask reports that something is broken or misbehaving.","--"),
 "3. Inquiry":("The ask seeks information or advice rather than code.","19.2"),
 "4. Validation":("The ask wants the agent to check code or its execution.","4.0"),
 "5. Delegation":("The ask hands off a written deliverable or an action in the environment.","16.5"),
 "6. Others":(None,"--"),  # single-row category
}

# ---- version sanity check ----
vfile = Path(args.dataset) / "VERSION"
if vfile.is_file():
    assert "1.0-20261008" in vfile.read_text(), "unexpected dataset version"
    print(f"[ok] dataset version: {vfile.read_text().strip()}")

# ============ POPULATION (classifier) ============
con = duckdb.connect()
con.execute(f"""
CREATE TEMP TABLE asks AS
SELECT s.id AS sid, cl.type AS ctype, cl.labels AS labels,
       CASE WHEN cl.labels IS NOT NULL AND len(cl.labels)>0 THEN cl.labels[1] END AS prim
FROM {SESS} s JOIN {CLS} cl ON cl.session_id = s.id
WHERE s.session_index = 0;
""")
n_first = con.sql("SELECT count(*) FROM asks").fetchone()[0]
n_empty = con.sql("SELECT count(*) FROM asks WHERE ctype IN ('missing','error')").fetchone()[0]
POP = n_first - n_empty
pop_cnt = {lab: con.sql(f"SELECT count(*) FROM asks WHERE prim='{lab}'").fetchone()[0]
           for _, lab, _, _, _, _ in ROWS}
pop_multi = con.sql("SELECT round(100.0*avg(CASE WHEN len(labels)>1 THEN 1 ELSE 0 END),1) "
                    "FROM asks WHERE prim IS NOT NULL").fetchone()[0]

# ============ SAMPLE (manual) ============
ann = json.loads(Path(args.manual).read_text())
code2lab = {code: lab for code, lab, _, _, _, _ in ROWS}
man_cnt = {lab: 0 for _, lab, _, _, _, _ in ROWS}
man_multi = 0
for r in ann:
    labs = r["annotations"][0]["labels"]
    if not labs:
        continue
    code = labs[0].split(" ", 1)[0]          # e.g. "3.2"
    man_cnt[code2lab[code]] += 1
    if len(labs) > 1:
        man_multi += 1
MAN = sum(man_cnt.values())

# multi-intent exact-set combinations (population), % of multi-intent asks
con.execute("""
CREATE TEMP TABLE multi AS
SELECT array_to_string(list_sort(labels), '+') AS combo
FROM asks WHERE labels IS NOT NULL AND len(labels) > 1;
""")
MULTI = con.sql("SELECT count(*) FROM multi").fetchone()[0]
def combo_pct(sig):
    n = con.sql(f"SELECT count(*) FROM multi WHERE combo = '{sig}'").fetchone()[0]
    return 100.0 * n / MULTI if MULTI else 0.0

# manual sample provenance (overlap with v1.0 first-sessions)
ids = json.loads(Path(args.sample).read_text())["session_ids"]
con.execute("CREATE TEMP TABLE s384(id VARCHAR)")
con.executemany("INSERT INTO s384 VALUES (?)", [(i,) for i in ids])
in_v1 = con.sql(f"SELECT count(*) FROM s384 WHERE id IN (SELECT id FROM {SESS})").fetchone()[0]
first_v1 = con.sql(f"SELECT count(*) FROM s384 WHERE id IN "
                   f"(SELECT id FROM {SESS} WHERE session_index=0)").fetchone()[0]

# category rollups
pop_cat, man_cat = OrderedDict(), OrderedDict()
for _, lab, main, _, _, _ in ROWS:
    pop_cat[main] = pop_cat.get(main, 0) + pop_cnt[lab]
    man_cat[main] = man_cat.get(main, 0) + man_cnt[lab]

def pct(n, tot): return 100.0 * n / tot if tot else 0.0

# ---------- CSV ----------
csv_path = OUT / "rq1_asktypes_distribution.csv"
with open(csv_path, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["main_category","sub_category","label",
                "sample_n","sample_pct","population_n","population_pct"])
    for code, lab, main, sub, _, ide in ROWS:
        w.writerow([main, sub, lab, man_cnt[lab], round(pct(man_cnt[lab],MAN),2),
                    pop_cnt[lab], round(pct(pop_cnt[lab],POP),2)])
    w.writerow(["TOTAL","","",MAN,100.0,POP,100.0])

# ---------- Markdown ----------
md = []
md.append("# RQ1 - Ask types\n")
md.append(f"- Population (classifier): first sessions - empty/error = **{POP:,}** labelled asks.")
md.append(f"- Sample (manual): **{MAN}** hand-coded sessions (validation sample, seed 123).")
md.append(f"- Multi-intent: manual {pct(man_multi,MAN):.1f}%, population {pop_multi}%.")
md.append(f"- Manual-sample provenance: {in_v1}/{len(ids)} of the 384 exist in v1.0; "
          f"{first_v1} are first-sessions in v1.0 (the sample mixes asks and rounds and "
          f"excludes review-requests; treat it as classifier validation).\n")
md.append("| Ask type | Sample # | Sample % | Pop # | Pop % |")
md.append("|---|---:|---:|---:|---:|")
cur = None
for code, lab, main, sub, _, ide in ROWS:
    if main != cur:
        cur = main; _, cide = CAT_DEF[main]
        md.append(f"| **{main}** | {man_cat[main]} | {pct(man_cat[main],MAN):.1f} | "
                  f"{pop_cat[main]:,} | {pct(pop_cat[main],POP):.1f} |")
    if not main.startswith("6."):
        md.append(f"| &nbsp;&nbsp;{sub.replace(chr(92)+'&','&')} | {man_cnt[lab]} | {pct(man_cnt[lab],MAN):.1f} | "
                  f"{pop_cnt[lab]:,} | {pct(pop_cnt[lab],POP):.1f} |")
md.append(f"| **Total** | {MAN} | 100.0 | {POP:,} | 100.0 |")
(OUT / "tables" / "rq1_asktypes.md").write_text("\n".join(md) + "\n")

# ---------- LaTeX: drop-in Table III (both columns filled) ----------
L = []
L.append("% Generated by scripts/06_rq1_asktypes.py -- do not edit by hand.")
L.append("\\begin{table*}[t]")
L.append("\\caption{Ask types, coded with an adapted subset of the behavioral intent "
         "taxonomy of Tang et al.~\\cite{tang2026programming}: we keep the labels that occur "
         "in session-initiating asks (6 main categories, 14 labels) and reword the definitions "
         "for the delegation setting. \\# and \\% refer to the primary label of each ask; "
         "main-category rows are subtotals. The sample columns report the manual labels of "
         "the \\nsample sampled asks; the population columns report the labels assigned by the "
         "validated classifier (\\sec{sec:rq1}) to all \\npopulation asks in the filtered "
         "population.}")
L.append("\\label{tab:rq1}")
L.append("\\centering")
L.append("\\footnotesize")
L.append("\\setlength{\\tabcolsep}{3pt}")
L.append("\\begin{tabularx}{\\textwidth}{l>{\\raggedright\\arraybackslash}Xrrrr}")
L.append("\\toprule")
L.append(" & & \\multicolumn{2}{c}{Sample} & \\multicolumn{2}{c}{Population} \\\\")
L.append(" & & \\multicolumn{2}{c}{(manual)} & \\multicolumn{2}{c}{(classifier)} \\\\")
L.append("\\cmidrule(lr){3-4} \\cmidrule(lr){5-6}")
L.append("Ask type (primary label) & Definition & \\# & \\% & \\# & \\% \\\\")
L.append("\\midrule")
def cell(n): return f"{n:,}"
cur = None
for code, lab, main, sub, sdef, ide in ROWS:
    if main != cur:
        cur = main; cdef, cide = CAT_DEF[main]
        if cdef is not None:  # multi-row category header
            L.append(f"\\textbf{{{main}}} & {cdef} & {man_cat[main]} & {pct(man_cat[main],MAN):.1f} "
                     f"& {cell(pop_cat[main])} & {pct(pop_cat[main],POP):.1f} \\\\")
    if main.startswith("6."):  # single-row category (Others)
        L.append(f"\\textbf{{{main}}} & {sdef} & {man_cnt[lab]} & {pct(man_cnt[lab],MAN):.1f} "
                 f"& {cell(pop_cnt[lab])} & {pct(pop_cnt[lab],POP):.1f} \\\\")
    else:
        L.append(f"\\quad {sub} & {sdef} & {man_cnt[lab]} & {pct(man_cnt[lab],MAN):.1f} "
                 f"& {cell(pop_cnt[lab])} & {pct(pop_cnt[lab],POP):.1f} \\\\")
    # add a midrule after the last sub of each category (before next category)
# insert midrules between categories
out = []
prev_main = None
for line in L:
    if line.startswith("\\textbf{") and prev_main is not None:
        out.append("\\midrule")
    if line.startswith("\\textbf{"):
        prev_main = line
    out.append(line)
L = out
L.append("\\midrule")
L.append(f"Total & & \\nsample & 100.0 & {cell(POP)} & 100.0 \\\\")
L.append("\\bottomrule")
L.append("\\end{tabularx}")
L.append("\\end{table*}")
(OUT / "tables" / "rq1_table3.tex").write_text("\n".join(L) + "\n")

# ---------- LaTeX macros (prose + table share one source) ----------
def f1(x): return f"{float(x):.1f}"
macros = {
 "npopulation": f"{POP:,}".replace(",", "{,}") + r"\xspace",
 "rqCodeAuthPct":  f1(pct(pop_cat["1. Code Authoring"], POP)),
 "rqFailRepPct":   f1(pct(pop_cat["2. Failure Reporting"], POP)),
 "rqInquiryPct":   f1(pct(pop_cat["3. Inquiry"], POP)),
 "rqValidPct":     f1(pct(pop_cat["4. Validation"], POP)),
 "rqDelegPct":     f1(pct(pop_cat["5. Delegation"], POP)),
 "rqOthersPct":    f1(pct(pop_cat["6. Others"], POP)),
 "rqNewImplPct":   f1(pct(pop_cnt["code_creation"], POP)),
 "rqIterModPct":   f1(pct(pop_cnt["code_change"], POP)),
 "rqCodeRevPct":   f1(pct(pop_cnt["review_code"], POP)),
 "rqGenKnowPct":   f1(pct(pop_cnt["question_general"], POP)),
 "rqValidSampPct": f1(pct(man_cat["4. Validation"], MAN)),
 "rqMultiPct":     f1(pop_multi),
 "rqComboChgSym":  f1(combo_pct("code_change+failure_symptom")),
 "rqComboChgTool": f1(combo_pct("code_change+dev_operation")),
 "rqComboChgLog":  f1(combo_pct("code_change+failure_log")),
 "rqComboNewTool": f1(combo_pct("code_creation+dev_operation")),
}
mac = ["% Generated by scripts/06_rq1_asktypes.py -- do not edit by hand.",
       "% \\input this file in the preamble, next to setting_variable.",
       "% Remove the \\npopulation line from setting_variable.tex to avoid a clash."]
for k, v in macros.items():
    mac.append("\\newcommand{\\" + k + "}{" + str(v) + "}")
(OUT / "tables" / "rq1_macros.tex").write_text("\n".join(mac) + "\n")
print("wrote: outputs/tables/rq1_macros.tex")

# ---------- console ----------
print(f"\nPopulation: {n_first:,} first - {n_empty:,} empty = {POP:,} labelled")
print(f"Manual sample: {MAN} coded   (in v1.0: {in_v1}/{len(ids)}, first-session in v1.0: {first_v1})")
print(f"\n{'row':32s}{'man#':>6}{'man%':>7}{'pop#':>10}{'pop%':>7}{'IDE%':>7}")
cur=None
for code, lab, main, sub, _, ide in ROWS:
    if main!=cur:
        cur=main; _,cide=CAT_DEF[main]
        print(f"{main:32s}{man_cat[main]:>6}{pct(man_cat[main],MAN):>7.1f}{pop_cat[main]:>10,}{pct(pop_cat[main],POP):>7.1f}{cide:>7}")
    if not main.startswith('6.'):
        print(f"  {sub[:30]:30s}{man_cnt[lab]:>6}{pct(man_cnt[lab],MAN):>7.1f}{pop_cnt[lab]:>10,}{pct(pop_cnt[lab],POP):>7.1f}{ide:>7}")
print(f"{'Total':32s}{MAN:>6}{100.0:>7.1f}{POP:>10,}{100.0:>7.1f}{'--':>7}")
print(f"\nwrote: outputs/rq1_asktypes_distribution.csv")
print(f"wrote: outputs/tables/rq1_asktypes.md")
print(f"wrote: outputs/tables/rq1_table3.tex")
