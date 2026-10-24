# Replication Package: "Fix This, Please"

Replication package for *"Fix This, Please": An Empirical Study of What Developers Ask
GitHub's Coding Agent to Do*, run on the AgentLogs dataset, revision `1.0-20261008`
(schema v1.0).

> Anonymous replication package (double-blind submission). No author names.

The package has two parts that together reproduce the study end to end:

```
fix-this-please-replication/
├── intent-classification/   # step 1: the ask/round classifier and its manual validation
└── analysis/                # step 2: the RQ1-RQ3 analysis built on the labels
```

## Part 1: intent-classification/

The intent classifier, the codebook (adapted from Tang et al.), and the manual coding
used to validate it. It produces `data/session_classifications.parquet`, the per-session
intent labels over the full population, along with the validation materials: the
384-session sample, the per-iteration annotations from five coders, the LLM-alignment
sample, and `measure_agreement.py`, which computes the inter-rater and classifier-vs-human
Cohen's and Fleiss' kappa. See `intent-classification/README.md`.

## Part 2: analysis/

The RQ1-RQ3 pipeline: the sampling frame, the ask-type distribution, cost in output
tokens, merge rate, change size, the follow-up rounds, and all of the statistics and
generated tables. See `analysis/README.md` for the full sequence.

## How the two parts connect

The analysis consumes the classifier output from part 1. We already include
`analysis/sample/rq1_task_labels.csv`, the per-task primary ask-type labels derived from
`intent-classification/data/session_classifications.parquet`, so the analysis runs without
re-classifying. To reproduce from scratch, run part 1 first, copy
`intent-classification/data/session_classifications.parquet` into `analysis/data/`
(gitignored there), and run the analysis pipeline.

We do not bundle the raw AgentLogs dataset, which is large and public; each part's
download step fetches revision `1.0-20261008`.

## Anonymity

Both parts are author-anonymous. There are no author names or affiliations, the coders are
numbered rather than named (1 to 5), and all code and commit authorship reads "Anonymous".
The sample asks are public excerpts of AgentLogs (CC BY 4.0; see the `DATA_LICENSE` files),
and the codebook is reused under MIT (see `intent-classification/data/codebook/LICENSE`).
