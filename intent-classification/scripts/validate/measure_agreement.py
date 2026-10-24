#%%
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("iteration", type=str)
ITERATION = parser.parse_args().iteration
ITERATION_DIR = ROOT / "data" / "validation" / f"iteration_{ITERATION}"
ANNOTATIONS_PATH = ITERATION_DIR / "annotations.json"
LLM_PATH = ITERATION_DIR / "annotations_llm.json"
LABELS_PATH = ITERATION_DIR / "labels.json"

#%%
records = json.loads(ANNOTATIONS_PATH.read_text(encoding="utf-8"))
subcategories = [
    label["sub_category"].split(" ", 1)[0]
    for label in json.loads(LABELS_PATH.read_text(encoding="utf-8"))
]
rows = []
for record in records:
    annotations = record["annotations"]
    for entry in annotations:
        selected = {label.split(" ", 1)[0] for label in entry["labels"]}
        for code in subcategories:
            rows.append({
                "session_id": record["id"],
                "annotator": entry["annotator"],
                "code": code,
                "present": int(code in selected),
            })
if LLM_PATH.is_file():
    llm_records = json.loads(LLM_PATH.read_text(encoding="utf-8"))
    llm_by_id = {
        record["id"]: record
        for record in llm_records
        if isinstance(record.get("labels"), list)
    }
    missing = [record["id"] for record in records if record["id"] not in llm_by_id]
    if missing:
        raise SystemExit(
            f"{LLM_PATH.name} is missing {len(missing)} sessions from {ANNOTATIONS_PATH.name}"
        )
    seen: set[str] = set()
    for record in records:
        if record["id"] in seen:
            continue
        seen.add(record["id"])
        selected = {
            label["sub_category"].split(" ", 1)[0]
            for label in llm_by_id[record["id"]]["labels"]
        }
        for code in subcategories:
            rows.append({
                "session_id": record["id"],
                "annotator": "llm",
                "code": code,
                "present": int(code in selected),
            })
decisions = pd.DataFrame(rows)
multiple = int(decisions.groupby("session_id")["annotator"].nunique().max()) > 2
if multiple:
    print("detected multiple annotators per session, using Fleiss' kappa")
else:
    print("no multiple annotators per session, using Cohen's kappa")
print()


def label_kappas(frame: pd.DataFrame) -> pd.Series:
    ranked = frame.sort_values(["session_id", "code", "annotator"]).copy()
    ranked["side"] = ranked.groupby(["session_id", "code"], sort=False).cumcount()
    paired = ranked.pivot(index=["session_id", "code"], columns="side", values="present")
    values = {}
    for code, group in paired.groupby(level="code", sort=False):
        left = group[0].to_numpy()
        right = group[1].to_numpy()
        if np.unique(np.concatenate([left, right])).size < 2:
            values[code] = np.nan
            continue
        values[code] = cohen_kappa_score(left, right)
    return pd.Series(values).reindex(subcategories)


annotators = sorted(decisions["annotator"].unique())
sessions_of = decisions.groupby("annotator")["session_id"].apply(set)
table = pd.DataFrame(index=annotators, columns=annotators, dtype=float)
for row in annotators:
    for col in annotators:
        if row == col:
            continue
        shared = sessions_of[row] & sessions_of[col]
        pair = decisions[
            decisions["session_id"].isin(shared) & decisions["annotator"].isin([row, col])
        ]
        table.loc[row, col] = float(label_kappas(pair).mean())

if multiple:
    fleiss = {}
    for code in subcategories:
        counts = (
            decisions[decisions["code"] == code]
            .groupby("session_id")["present"]
            .agg(["sum", "count"])
        )
        counts = counts[counts["count"] >= 2]
        present = counts["sum"].to_numpy()
        total = counts["count"].to_numpy()
        absent = total - present
        agreement = (present * (present - 1) + absent * (absent - 1)) / (total * (total - 1))
        ratings = present.sum() + absent.sum()
        chance = (present.sum() / ratings) ** 2 + (absent.sum() / ratings) ** 2
        fleiss[code] = np.nan if chance == 1 else (agreement.mean() - chance) / (1 - chance)
    per_label = pd.Series(fleiss).reindex(subcategories)
else:
    per_label = label_kappas(decisions)
if len(annotators) > 2:
    for name in annotators:
        if multiple:
            kappa = float(table.loc[name, annotators].mean())
        else:
            subset = decisions[decisions["session_id"].isin(sessions_of[name])]
            kappa = float(label_kappas(subset).mean())
        table.loc[name, "all"] = kappa
        table.loc["all", name] = kappa
    table.loc["all", "all"] = float(per_label.mean())

rendered = table.map(lambda value: f"{value:.3f}")
for name in annotators:
    rendered.loc[name, name] = "-"
print(rendered.to_string())
print()
label_table = pd.DataFrame({
    "code": subcategories,
    "agreement": per_label.reindex(subcategories).to_numpy(),
    "occurrences": decisions.groupby("code")["present"].sum().reindex(subcategories).to_numpy(),
}).sort_values("agreement", ascending=False)
print(label_table.to_string(index=False, formatters={"agreement": "{:.3f}".format}))
if len(annotators) <= 2:
    print(f"all annotators: {float(per_label.mean()):.3f}")

# %%
