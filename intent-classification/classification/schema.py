from typing import TypedDict

import pyarrow as pa


class ClassificationReasoning(TypedDict):
    label: str
    reasoning: str


class Classification(TypedDict):
    session_id: str
    type: str
    labels: list[str] | None
    reasoning: list[ClassificationReasoning] | None


CLASSIFICATION_SCHEMA = pa.schema([
    pa.field("session_id", pa.string(), nullable=False),
    pa.field("type", pa.string(), nullable=False),
    pa.field("labels", pa.list_(pa.string())),
    pa.field(
        "reasoning",
        pa.list_(
            pa.struct([
                pa.field("label", pa.string(), nullable=False),
                pa.field("reasoning", pa.string(), nullable=False),
            ])
        ),
    ),
])
