from pathlib import Path

from huggingface_hub import snapshot_download

ROOT = Path(__file__).resolve().parents[2]
REPO_ID = "risenlab/agentlogs"
REVISION = "0.2"
LOCAL_DIR = ROOT / "data" / "dataset_0.2"

LOCAL_DIR.mkdir(parents=True, exist_ok=True)
path = snapshot_download(
    repo_id=REPO_ID,
    repo_type="dataset",
    revision=REVISION,
    local_dir=LOCAL_DIR,
)
print(path)
