import json
from functools import cache
from pathlib import Path

from agentlogs.schema import AgentSession

ROOT = Path(__file__).resolve().parents[1]
CLASSIFICATION_PATH = ROOT / "data" / "codebook"


def load_codebook() -> str:
    return (CLASSIFICATION_PATH / "codebook.md").read_text(encoding="utf-8")


def load_response_format() -> dict:
    return json.loads((CLASSIFICATION_PATH / "response_schema.json").read_text(encoding="utf-8"))


@cache
def load_direct_classification() -> dict[str, list[dict[str, str]]]:
    path = CLASSIFICATION_PATH / "direct_classification.json"
    return json.loads(path.read_text(encoding="utf-8"))


def get_direct_classification(session: AgentSession) -> list[dict[str, str]] | None:
    """Return the direct classification for this event type, or None when it is not set."""
    event = session["event"]
    if not event:
        return None
    return load_direct_classification().get(event["type"])


def load_valid_labels() -> set[tuple[str, str]]:
    labels = json.loads((CLASSIFICATION_PATH / "labels.json").read_text(encoding="utf-8"))
    return {
        (label["main_category"], label["sub_category"])
        for label in labels
    }


def parse_response_labels(content: str, allowed: set[tuple[str, str]]) -> list[dict[str, str]]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as error:
        raise ValueError(str(error)) from error
    labels = parsed.get("labels") if isinstance(parsed, dict) else None
    if not isinstance(labels, list) or not labels:
        raise ValueError("empty classification labels")
    stored: list[dict[str, str]] = []
    for label in labels:
        if not isinstance(label, dict):
            raise ValueError("invalid classification label")
        reasoning = label.get("reasoning")
        main_category = label.get("main_category")
        sub_category = label.get("sub_category")
        if not isinstance(reasoning, str) or reasoning == "":
            raise ValueError("classification label is missing reasoning")
        if not isinstance(main_category, str) or not isinstance(sub_category, str):
            raise ValueError("invalid classification label")
        if (main_category, sub_category) not in allowed:
            raise ValueError(f"invalid classification label {main_category} / {sub_category}")
        stored.append({
            "reasoning": reasoning,
            "main_category": main_category,
            "sub_category": sub_category,
        })
    return stored
