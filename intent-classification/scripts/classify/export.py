import json
import os
import sqlite3
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from classification.schema import CLASSIFICATION_SCHEMA
from classification.state import STATE_PATH

BATCH = 10000

label_map = {
    (entry["main_category"], entry["sub_category"]): entry["label"]
    for entry in json.loads(
        (ROOT / "data" / "codebook" / "label_map.json").read_text()
    )
}

destination = ROOT / "data" / "session_classifications.parquet"
destination.parent.mkdir(parents=True, exist_ok=True)
temporary = destination.with_name(destination.name + ".tmp")
temporary.unlink(missing_ok=True)

db = sqlite3.connect(f"file:{STATE_PATH}?mode=ro", uri=True)
cursor = db.execute(
    """
    SELECT session_id, type, labels
    FROM classification
    ORDER BY session_id
    """
)

writer = pq.ParquetWriter(temporary, CLASSIFICATION_SCHEMA)
written = 0
closed = False
finished = False
try:
    while True:
        rows = cursor.fetchmany(BATCH)
        if not rows:
            break
        session_ids: list[str] = []
        types: list[str] = []
        labels_col: list[list[str] | None] = []
        reasoning_col: list[list[dict[str, str]] | None] = []
        for session_id, row_type, labels_text in rows:
            session_ids.append(session_id)
            types.append(row_type)
            if row_type == "error" or labels_text is None:
                labels_col.append(None)
                reasoning_col.append(None)
            else:
                stored = json.loads(labels_text)
                names: list[str] = []
                reasons: list[dict[str, str]] = []
                for item in stored:
                    name = label_map[(item["main_category"], item["sub_category"])]
                    names.append(name)
                    reasons.append({"label": name, "reasoning": item["reasoning"]})
                labels_col.append(names)
                reasoning_col.append(reasons)
        writer.write_table(pa.table(
            {
                "session_id": session_ids,
                "type": types,
                "labels": labels_col,
                "reasoning": reasoning_col,
            },
            schema=CLASSIFICATION_SCHEMA,
        ))
        written += len(rows)
    writer.close()
    closed = True
    os.replace(temporary, destination)
    finished = True
finally:
    db.close()
    if not closed:
        writer.close()
    if not finished:
        temporary.unlink(missing_ok=True)

print(f"Wrote {written} rows to {destination}", flush=True)
