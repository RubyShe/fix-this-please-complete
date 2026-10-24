import argparse
import json
import zipfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser()
parser.add_argument("zip_name")
parser.add_argument("iteration", type=int)
args = parser.parse_args()
EXPORT_PATH = ROOT / "data" / args.zip_name
OUTPUT_PATH = ROOT / "data" / "validation" / f"iteration_{args.iteration}" / "annotations.json"
INCLUDED_STATES = {"FINISHED", "IN_PROGRESS"}
SKIP_USERS = {"admin", "CURATION_USER"}


def read_selected_labels(data: bytes) -> list[str]:
    cas = json.loads(data)
    by_id = {fs["%ID"]: fs for fs in cas["%FEATURE_STRUCTURES"]}
    for fs in cas["%FEATURE_STRUCTURES"]:
        if fs.get("%TYPE") != "custom.DocumentLabel":
            continue
        ref = fs.get("@Label")
        if not ref:
            return []
        return list(by_id[ref].get("%ELEMENTS") or [])
    return []


with zipfile.ZipFile(EXPORT_PATH) as archive:
    project = json.loads(archive.read("exportedproject.json"))
    members = set(archive.namelist())
    annotators_by_document: dict[str, list[str]] = defaultdict(list)
    for document in project["annotation_documents"]:
        if document["state"] in INCLUDED_STATES and document["user"] not in SKIP_USERS:
            annotators_by_document[document["name"]].append(document["user"])
    records = []
    for source in project["source_documents"]:
        name = source["name"]
        annotations = []
        for annotator in annotators_by_document[name]:
            member = f"annotation/{name}/{annotator}.json"
            labels = read_selected_labels(archive.read(member)) if member in members else []
            annotations.append({"annotator": annotator, "labels": labels})
        records.append({"id": name.removesuffix(".pdf"), "annotations": annotations})

OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_PATH.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(records)} documents to {OUTPUT_PATH}")
