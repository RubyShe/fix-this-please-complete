# Replication Package: "Fix This, Please"

Empirical study of what developers ask GitHub's Copilot cloud agent to do,
run on the **AgentLogs** dataset, revision **`1.0-20261008`** (schema v1.0).

> Anonymous replication package (double-blind submission). No author names.

## Layout
- `scripts/`: the pipeline (download, RQ1/RQ2/RQ3 analysis, stats). Rerunnable.
- `sample/`: the per-task ask-type labels that RQ2 and RQ3 group by.
- `outputs/`: generated tables and distributions. Large artifacts are gitignored.
- `data/`: raw dataset and intent classification. Gitignored; see **Inputs**.

## Inputs (gitignored, obtained separately)
- `data/dataset_v1.0/`: AgentLogs `1.0-20261008`, pulled by `scripts/01_download_v1.py`.
- `data/session_classifications.parquet`: the published AgentLogs intent
  classification (GPT-6 Luna). It labels every session with the adapted Tang et al.
  codebook (6 main categories, 14 labels) and marks empty asks as `type='missing'`.
  Copy it here from the intent-classification release.
- `data/codebook/*.json`: the codebook (label map, response schema) from that release.

## How to reproduce
```bash
pip install -r requirements.txt
python3 scripts/01_download_v1.py                 # AgentLogs 1.0-20261008 (except the 63GB logs)

# RQ1 - ask types
python3 scripts/06_rq1_asktypes.py                # population ask-type distribution (Table III)
python3 scripts/07_rq1_task_labels.py             # per-task primary labels (used by RQ2/RQ3)
python3 scripts/09_rq1_prompt_characterization.py # artifact-reference share + prompt length
python3 scripts/12_rq1_sample_characterization.py # distinct repos/creators, entry points, review-request share

# RQ2 - cost and outcome
python3 scripts/02_rq2_metrics_v1.py              # per-task rounds, merge status, change size
python3 scripts/04_rq2_tableIV_stats.py           # merge-rate + change-size stats per ask type
python3 scripts/08_rq2_tokens.py --fetch          # per-session tokens from the logs (column-projected)
python3 scripts/11_tokens_primary.py              # output tokens as the cost metric: Table II + KW/MW/Cliff

# RQ3 - follow-up rounds
python3 scripts/03_classify_commenters.py         # bot/human commenter lists
python3 scripts/05_rq3_followup_detector.py       # round detection
python3 scripts/10_rq3_rounds.py --timeline       # round intents (Table V), repeat/takeover, token decomposition
```

## RQ2 cost metric
We measure cost in output (completion) tokens (`scripts/11_tokens_primary.py`), not
premium-request credits. Credits are billed per session, so they sit at about one per
task and say nothing about whether a change was small or large; we report them only as
a secondary figure. Token usage is recorded for 71.6% of tasks (the sessions whose logs
carry usage); we treat the rest as missing, the same way we handle change size.

## RQ1 ask types (classification-based)
The unit for RQ1 is the session-initiating ask, that is, the first session of each task.
Rather than hand-code at scale, we use the published intent classification: it already
labels every session and flags the empty ones. The only selection is the first session
of each task, minus the empty and error sessions (`type in ('missing','error')`, labels
NULL).

The primary label is the first label the classifier returns, since it orders them by
dominance. The full breakdown is in
[`outputs/tables/rq1_asktypes.md`](outputs/tables/rq1_asktypes.md) and
[`outputs/rq1_asktypes_distribution.csv`](outputs/rq1_asktypes_distribution.csv).

Funnel: 353,432 first sessions, minus 28,737 empty or error, leaves **324,695 labelled asks**.

| Main category | # | % |
|---|---:|---:|
| 1. Code Authoring | 160,345 | 49.4 |
| 2. Failure Reporting | 68,368 | 21.1 |
| 4. Validation | 43,337 | 13.3 |
| 5. Delegation | 34,008 | 10.5 |
| 3. Inquiry | 14,950 | 4.6 |
| 6. Others | 3,687 | 1.1 |
| **Total** | **324,695** | **100.0** |

Most asks tell the agent to write or change code (49%), then to fix failures (21%).
Questions are uncommon: Inquiry is 4.6%. A third of asks (35.1%) carry more than one
intent.

## A note on filtering
The heavier F1-F4 manual pipeline from the original plan is not necessary on this data.
The classifier already flags the empty asks (`missing`, 8.1% of first sessions), which is
F2. We do not apply the original F3 (playground repositories) or F4 (deduplication) steps;
the paper's filtering is F1 and F2 only. Playground repos and retried duplicate prompts are
left in the population rather than removed. The only selection we apply is first-session,
minus empty or error.

## Reproducibility notes
- The dataset revision is pinned, and `06` asserts `1.0-20261008` after loading.
- RQ1 runs on the published classification (`session_classifications.parquet`); the
  taxonomy and codebook come from the intent-classification release.
- Merge status and change size (RQ2) come from the pinned snapshot, not a live API.

## Status
Every analysis in the submission is in place.

- RQ1: the ask-type distribution (`06`), per-task labels (`07`), prompt
  characterization (`09`), sample characterization (`12`), and the inter-rater agreement
  (kappa) from the coding iterations in the intent-classification validation set.
- RQ2: per-task metrics (`02`), merge-rate and change-size stats (`04`), and the
  output-token cost metric with Kruskal-Wallis, Mann-Whitney, and Cliff's delta (`08`, `11`).
- RQ3: commenter classification (`03`), round detection (`05`), and the round intents,
  repeat rate, convergence and takeover, and token cost decomposition (`10`).

Generated tables and macros live in `outputs/tables/`. The paper's tables are reproduced
there: `rq1_table3.tex` (Table III), `rq2_table_outcomes.tex` (RQ2 outcomes), and
`rq3_tableV.tex` (RQ3 rounds). A few legacy credit-based artifacts remain
(`rq2_tokens_by_type.csv` and the cost-per-merged and wasted-credit macros in
`rq2_macros.tex`); the token outputs supersede them, and the paper does not use them.
