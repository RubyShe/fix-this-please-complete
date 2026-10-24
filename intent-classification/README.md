# AgentLogs intent classification

Intent labels for sessions in [risenlab/agentlogs](https://huggingface.co/datasets/risenlab/agentlogs) release `1.0-20261008`, classified using GPT-6 Luna and published as [`data/session_classifications.parquet`](data/session_classifications.parquet).

## Schema

| Column | Type | Description |
| --- | --- | --- |
| `session_id` | string, required | AgentLogs session id. |
| `type` | string, required | See table below. |
| `labels` | list of string, null for `missing` and `error` | See [labels](#labels). |
| `reasoning` | list of `{label, reasoning}`, null for `missing` and `error` | Each `reasoning` is the short justification stored with that label. |

635,886 sessions. Shares below are of that total.

| `type` | Description | Sessions | Share |
| --- | --- | ---: | ---: |
| `prompt` | LLM classification of session prompt/problem statement. | 539,216 | 84.80% |
| `direct` | The session event type has fixed labels (today, only `review-request` → `["review_code"]`). | 35,727 | 5.62% |
| `missing` | No session prompt/problem statement to classify. | 60,942 | 9.58% |
| `error` | LLM classification failed. | 1 | <0.01% |

## Labels

Labels name the action the user expects the agent to take, classified from the problem statement and the prompt. Shares are of the 574,943 `prompt` and `direct` sessions. `missing` and `error` have no labels, so they are left out of that total. A turn with more than one intent gets every applicable label, so the shares sum to more than 100%.

| Label | Meaning | Sessions | Share |
| --- | --- | ---: | ---: |
| `code_creation` | Write code that is not there yet (a new feature, module, or capability). | 81,601 | 14.19% |
| `code_change` | Change or constrain code already being written. | 253,567 | 44.10% |
| `code_unspecified` | Write or change code, without enough context to tell new code from a change. | 3,472 | 0.60% |
| `failure_log` | Fix a failure given as a log, stack trace, or compiler output. | 46,951 | 8.17% |
| `failure_symptom` | Fix a failure described in words. | 93,301 | 16.23% |
| `failure_unspecified` | Fix a failure from neither a log or symptom description ("fix it", "still broken"). | 17,726 | 3.08% |
| `question_plan` | Plan what to do next, before writing code. | 23,478 | 4.08% |
| `question_project` | Explain how this project works or what it currently does. | 29,237 | 5.09% |
| `question_general` | Answer something that does not depend on this project. | 3,732 | 0.65% |
| `review_code` | Inspect code, logic, or config without running it. | 67,471 | 11.74% |
| `review_runtime` | Check a run, test output, or terminal. | 16,377 | 2.85% |
| `documentation` | Write a doc, note, or comment. | 47,895 | 8.33% |
| `dev_operation` | Run, build, commit, deploy, take an action on GitHub, or otherwise operate the toolchain. | 101,586 | 17.67% |
| `other` | No clear intent. The turn is empty, off-topic, or a bare "ok" with no context. | 7,509 | 1.31% |

## Using the classifications

[`scripts/example_analysis.ipynb`](scripts/example_analysis.ipynb) demonstrates how to join the classifications in [`data/session_classifications.parquet`](data/session_classifications.parquet) to AgentLogs and further analyze it with DuckDB, Polars, and streaming.

## What is classified

[`classification/prompts.py`](classification/prompts.py) (`build_prompt`) builds the text for one session. `direct` rows (`review-request`) skip this text. `missing` rows have neither source in step 1. `error` rows had text, and the model call failed. `labels` and `reasoning` are null for `missing` and `error`.

1. Read the current session's `prompt` when that string is non-empty. It is often unset. Walk the session log in `entry_index` order and take the first user message that contains a `<problem_statement>`.
2. If the statement body repeats the prompt, ignoring case and whitespace, drop the prompt. Wrap what remains in `<current>`, as `<request>`, `<prompt>`, or both.
3. Clean the log message. Remove closed `memories`, `repository_memories`, `reminder`, and `replying_to_comments` tags. After the statement, also remove `repository_context` and a "Steps to Follow" numbered list. Cut the combined turn to 16,000 characters: drop `<comment_old>` from the front, then keep the first 30% of that budget and the tail.
4. If this session is not the first in its task, the previous session is the one with the preceding `session_index`. Build its user text the same way, with an 8,000-character budget, and wrap it in `<prev_user>`.
5. For that previous session, use its `error` string when one is set. Otherwise use the last assistant reply in its log: `delta.content` from a choice whose `finish_reason` is `stop`, skipping replies that contain `<pr_title>` or `<pr_description>`. Cut that text to 2,000 characters, keeping the first 30% of that budget and the tail, and wrap it in `<prev_assistant>`.

## Replicating the classification

```bash
pip install -r scripts/classify/requirements.txt
cp .env.example .env

python scripts/classify/download_dataset.py
python scripts/classify/prepare.py
python scripts/classify/run.py
python scripts/classify/export.py
```

Copy `.env.example` to `.env` and set `OPENAI_API_KEY`. `download_dataset.py` fetches the `1.0-20261008` snapshot. `run.py` uses one key, waits when the response-header budget is exhausted, and retries rate limits. `export.py` writes `data/session_classifications.parquet`.

## Validation

The codebook was impoved and validated on a fixed sample from the `0.2` release. Event types with a direct label set are left out. `draw_sample.py` keeps the first 384 eligible sessions from a shuffle with seed `123`, and writes Markdown under `data/validation/sample`. These samples were manually annotated over several iterations of the codebook using the open-source [INCEpTION](https://github.com/inception-project/inception) annotation tool. `parse_export.py` reads an export from this tool into `data/validation/iteration_<n>/annotations.json`. `measure_agreement.py` prints Cohen's kappa, or Fleiss' kappa when a session has more than two annotators. The last iteration (`iteration_4`) also contains annotations generated using GPT-6 Luna, to measure agreement. Before that run, the codebook's context and focus instructions were slightly adapted so the model would better recognize which part of the prompt to focus on. The code descriptions were left as they were. This was done on a separate sample of 30 sessions in [`data/llm_alignment`](data/llm_alignment).

```bash
pip install -r scripts/validate/requirements.txt

python scripts/validate/download_dataset.py
python scripts/validate/draw_sample.py
python scripts/validate/parse_export.py <export.zip> <iteration>
python scripts/validate/measure_agreement.py <iteration>
```

## License

Code in this repository is [MIT](LICENSE). `codebook.md`, `labels.json`, and `response_schema.json` were taken from [empirical-conversational-programming](https://github.com/ND-SaNDwichLAB/empirical-conversational-programming) (`intent_classification/`) and adapted to this dataset. They are &copy; 2026 Ningzhi Tang, used under the [MIT License](data/codebook/LICENSE). Session samples in [`data/validation/sample`](data/validation/sample) and [`data/llm_alignment/sample`](data/llm_alignment/sample) are excerpts from [risenlab/agentlogs](https://huggingface.co/datasets/risenlab/agentlogs) release `0.2`. Each of those folders includes that release's `DATA_LICENSE` (CC BY 4.0).
