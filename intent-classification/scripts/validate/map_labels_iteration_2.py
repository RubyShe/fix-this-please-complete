import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE_PATH = ROOT / "data" / "validation" / "iteration_2" / "annotations.json"
OUTPUT_PATH = ROOT / "data" / "validation" / "iteration_2_mapped" / "annotations.json"
MAPPING = {
    "1.3": "1.2 Code Authoring - Iterative Modification",
    "2.3": "2.2 Failure Reporting - Symptom Description",
    "4.1": None,
    "4.2": None,
    "7.1": None,
    "7.2": None,
    "7.3": "2.2 Failure Reporting - Symptom Description",
    "7.4": "1.2 Code Authoring - Iterative Modification",
    "7.5": None,
    "8.1": None,
}

records = json.loads(SOURCE_PATH.read_text(encoding="utf-8"))
for record in records:
    for entry in record["annotations"]:
        mapped = []
        seen = set()
        for label in entry["labels"]:
            code = label.split(" ", 1)[0]
            if code in MAPPING:
                label = MAPPING[code]
                if label is None:
                    continue
            if label in seen:
                continue
            seen.add(label)
            mapped.append(label)
        entry["labels"] = mapped

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(records)} documents to {OUTPUT_PATH}")
