import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from classification.dashboard import Dashboard
from classification.labels import load_codebook, load_response_format, load_valid_labels, parse_response_labels
from classification.openai import APIError, OpenAIAPI
from classification.prompts import LABEL_ATTEMPTS
from classification.state import claim_job, fail_job, finish_job, open_state, release_running

CONCURRENCY = 100
SERVICE_TIER = "flex"


async def run() -> None:
    db, _lock = open_state()
    release_running(db)
    api = OpenAIAPI(api_key, connections=CONCURRENCY)
    counts = db.execute(
        """
        SELECT COUNT(*),
               COALESCE(SUM(input_tokens), 0),
               COALESCE(SUM(output_tokens), 0),
               COALESCE(SUM(cost), 0)
        FROM classification
        WHERE type = 'prompt'
        """
    ).fetchone()
    finished = int(counts[0])
    input_tokens = int(counts[1])
    output_tokens = int(counts[2])
    cost = float(counts[3])
    pending = int(db.execute("SELECT COUNT(*) FROM queue WHERE status = 'pending'").fetchone()[0])
    errors = int(db.execute("SELECT COUNT(*) FROM queue WHERE status = 'error'").fetchone()[0])
    system = load_codebook()
    schema = load_response_format()
    allowed = load_valid_labels()
    dashboard = Dashboard(
        api, finished, errors, input_tokens, output_tokens, cost, pending,
    )
    view = asyncio.create_task(dashboard.run())

    async def classify() -> None:
        while True:
            job = claim_job(db)
            if job is None:
                return
            session_id, prompt = job
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ]
            last_error = "classification failed"
            record = None
            try:
                for _ in range(LABEL_ATTEMPTS):
                    completion = await api.complete(
                        messages,
                        response_format=schema,
                        service_tier=SERVICE_TIER,
                    )
                    choice = completion.response["choices"][0]["message"]
                    content = choice.get("content") if isinstance(choice, dict) else None
                    if not isinstance(content, str) or content == "":
                        last_error = "empty classification response"
                        continue
                    try:
                        labels = parse_response_labels(content, allowed)
                    except ValueError as error:
                        last_error = str(error)
                        continue
                    record = {
                        "session_id": session_id,
                        "labels": labels,
                        "input_tokens": completion.input_tokens,
                        "output_tokens": completion.output_tokens,
                        "cost": completion.cost,
                        "model": completion.model,
                    }
                    break
            except APIError as error:
                fail_job(db, session_id, str(error))
                dashboard.fail()
                continue
            if record is None:
                fail_job(db, session_id, last_error)
                dashboard.fail()
                continue
            finish_job(db, record)
            dashboard.add(record)

    tasks = [asyncio.create_task(classify()) for _ in range(CONCURRENCY)]
    try:
        await asyncio.gather(*tasks)
    finally:
        view.cancel()
        for task in tasks:
            task.cancel()
        await asyncio.gather(view, *tasks, return_exceptions=True)
        await api.close()


load_dotenv(ROOT / ".env")
api_key = os.environ.get("OPENAI_API_KEY", "").strip()
if not api_key:
    raise SystemExit("OPENAI_API_KEY is missing from .env")
try:
    asyncio.run(run())
except APIError as error:
    raise SystemExit(str(error)) from error
