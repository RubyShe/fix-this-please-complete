import html
import json
import random
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from classification.labels import load_direct_classification
from classification.prompts import (
    CURRENT_LIMIT,
    PREVIOUS_LIMIT,
    build_assistant_turn,
    build_classification_message,
    build_user_turn,
)

DATASET = ROOT / "data" / "dataset_0.2"
SEED = 123
SAMPLE_SIZE = 384
OUTPUT = ROOT / "data" / "validation" / "sample"


@dataclass
class Session:
    id: str
    prompt: str | None
    log_found: bool
    event_type: str | None
    error: str | None
    previous_id: str | None

TURN_TAGS = ("prev_user", "prev_assistant", "current")
INNER_TAGS = ("request", "prompt", "problem_statement", "comment_new")
HEADER_TAGS = {
    "prev_user": "h2",
    "prev_assistant": "h2",
    "current": "h2",
    "request": "h3",
    "prompt": "h3",
}

PAGE_CSS = """
body {
  margin: 0;
  font: 16px/1.45 sans-serif;
  color: #1a1a1a;
}
h1 {
  margin: 0;
  padding: 1.25rem 1.5rem;
}
.turn h2,
.turn h3 {
  margin: 0.75rem 0 0.35rem;
  font-family: ui-monospace, monospace;
  font-weight: 600;
  line-height: 1.3;
}
.turn h2 { font-size: 1.15rem; }
.turn h3 { font-size: 1rem; }
.turn {
  box-sizing: border-box;
  width: 100%;
  margin: 0;
  padding: 0.8rem 1.15rem;
}
.turn pre,
.region pre {
  margin: 0;
  white-space: pre-wrap;
  word-wrap: break-word;
  font: 14px/1.45 ui-monospace, monospace;
}
.region {
  margin: 0.5rem 0.35rem;
  padding: 0.45rem 0.65rem;
}
.current-user { background: #b7dbf6; }
.current-request { background: #b7dbf6; }
.current-statement { background: #ffe7a8; }
.prev-comment { background: #f4eee8; }
.current-comment { background: #fad0b0; }
.prev-prompt { background: #e7f1ea; }
.current-prompt { background: #b6e6c9; }
""".strip()


def line_tag(line: str) -> str | None:
    text = line.strip()
    if len(text) < 3 or text[0] != "<" or text[-1] != ">":
        return None
    name = text[1:-1]
    if name.startswith("/"):
        name = name[1:]
        if name in TURN_TAGS or name in INNER_TAGS:
            return f"/{name}"
        return None
    if name in TURN_TAGS or name in INNER_TAGS:
        return name
    return None


def css_for(turn: str | None, stack: list[str], tag: str | None) -> str | None:
    if turn == "prev_assistant" or tag in ("prev_assistant", "/prev_assistant"):
        return "prev-assistant"
    side = "prev" if turn == "prev_user" or tag == "prev_user" else None
    if turn == "current" or tag == "current":
        side = "current"
    if side is None:
        return None
    closing_turn = tag is not None and tag.startswith("/") and tag[1:] in TURN_TAGS
    if tag in TURN_TAGS or closing_turn:
        return f"{side}-frame"
    if "prompt" in stack:
        return f"{side}-prompt"
    if "comment_new" in stack and "problem_statement" in stack:
        return f"{side}-comment"
    if "problem_statement" in stack:
        return f"{side}-statement"
    if "request" in stack:
        return f"{side}-request"
    return f"{side}-frame"


def prompt_bands(prompt: str) -> list[tuple[str | None, str]]:
    bands: list[tuple[str | None, str]] = []
    turn: str | None = None
    stack: list[str] = []
    buf: list[str] = []
    current: str | None = None

    def flush() -> None:
        if buf:
            bands.append((current, "\n".join(buf)))
            buf.clear()

    for line in prompt.split("\n"):
        tag = line_tag(line)
        if tag in INNER_TAGS:
            stack.append(tag)
        css = css_for(turn, stack, tag)
        if css != current:
            flush()
            current = css
        buf.append(line)
        if tag in TURN_TAGS:
            turn = tag
        elif tag is not None and tag.startswith("/") and tag[1:] in TURN_TAGS and turn == tag[1:]:
            turn = None
            stack.clear()
        elif tag is not None and tag.startswith("/") and tag[1:] in stack:
            closing = tag[1:]
            while stack and stack[-1] != closing:
                stack.pop()
            if stack:
                stack.pop()
    flush()
    return bands


def render_block(text: str) -> str:
    pieces: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if buf:
            pieces.append(f"<pre>{html.escape(chr(10).join(buf))}</pre>")
            buf.clear()

    for line in text.split("\n"):
        tag = line_tag(line)
        name = tag[1:] if tag is not None and tag.startswith("/") else tag
        if name in HEADER_TAGS:
            if tag is not None and tag.startswith("/"):
                continue
            flush()
            level = HEADER_TAGS[name]
            pieces.append(f"<{level}>{html.escape(line.strip())}</{level}>")
            continue
        buf.append(line)
    flush()
    return "\n".join(pieces)


def band_turn(css: str | None) -> str | None:
    if css == "prev-assistant":
        return "prev-assistant"
    if css is not None and css.startswith("prev-"):
        return "prev-user"
    if css is not None and css.startswith("current-"):
        return "current-user"
    return None


def in_request(css: str | None) -> bool:
    return css is not None and (
        css.endswith("-request") or css.endswith("-statement") or css.endswith("-comment")
    )


def prompt_html(session_id: str, prompt: str) -> str:
    bands = prompt_bands(prompt)
    parts: list[str] = []
    index = 0
    while index < len(bands):
        turn = band_turn(bands[index][0])
        group: list[tuple[str | None, str]] = []
        while index < len(bands) and band_turn(bands[index][0]) == turn:
            group.append(bands[index])
            index += 1
        inner: list[str] = []
        cursor = 0
        while cursor < len(group):
            css, text = group[cursor]
            if in_request(css):
                side = "prev" if css.startswith("prev-") else "current"
                chunks: list[str] = []
                saw_request = False
                while cursor < len(group) and in_request(group[cursor][0]):
                    piece_css, piece = group[cursor]
                    if piece_css.endswith("-request"):
                        saw_request = True
                        rendered = render_block(piece)
                        if rendered:
                            chunks.append(rendered)
                        cursor += 1
                        continue
                    statement: list[str] = []
                    while cursor < len(group) and group[cursor][0] is not None and (
                        group[cursor][0].endswith("-statement") or group[cursor][0].endswith("-comment")
                    ):
                        nested_css, nested = group[cursor]
                        rendered = render_block(nested)
                        if not rendered:
                            cursor += 1
                            continue
                        if nested_css.endswith("-comment"):
                            statement.append(f'<div class="region {nested_css}">{rendered}</div>')
                        else:
                            statement.append(rendered)
                        cursor += 1
                    chunks.append(
                        f'<div class="region {piece_css}">\n' + "\n".join(statement) + "\n</div>"
                    )
                body = "\n".join(chunks)
                if saw_request:
                    inner.append(f'<div class="region {side}-request">\n{body}\n</div>')
                else:
                    inner.append(body)
                continue
            rendered = render_block(text)
            if rendered and css is not None and css.endswith("-prompt"):
                inner.append(f'<div class="region {css}">{rendered}</div>')
            elif rendered:
                inner.append(rendered)
            cursor += 1
        klass = "turn" if turn is None else f"turn {turn}"
        parts.append(f'<div class="{klass}">\n' + "\n".join(inner) + "\n</div>")
    title = html.escape(session_id)
    body = "\n".join(parts)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
{PAGE_CSS}
</style>
</head>
<body>
<h1>{title}</h1>
{body}
</body>
</html>
"""


def log_targets(
    session_ids: list[str],
    sessions: dict[str, Session],
) -> tuple[set[str], set[str]]:
    """Sessions whose logs the prompt needs, and previous sessions that may have an assistant reply."""
    needed: set[str] = set()
    assistant_ids: set[str] = set()
    for session_id in session_ids:
        session = sessions[session_id]
        if session.log_found:
            needed.add(session_id)
        previous_id = session.previous_id
        if previous_id and sessions[previous_id].log_found:
            needed.add(previous_id)
            if sessions[previous_id].error is None:
                assistant_ids.add(previous_id)
    return needed, assistant_ids


def first_eligible(
    order: list[str],
    sample_size: int,
    sessions: dict[str, Session],
    user_texts: dict[str, list[str]],
) -> list[str] | None:
    chosen: list[str] = []
    for session_id in order:
        session = sessions[session_id]
        turn, _ = build_user_turn(user_texts.get(session_id, []), session.prompt, CURRENT_LIMIT)
        if turn is None:
            continue
        chosen.append(session_id)
        if len(chosen) == sample_size:
            chosen.sort()
            return chosen
    return None


def draw_sample(
    dataset: Path,
    seed: int,
    sample_size: int,
) -> tuple[list[str], dict[str, Session], dict[str, list[str]], dict[str, str]]:
    excluded = set(load_direct_classification())
    connection = duckdb.connect()
    print("Loading sessions", flush=True)
    session_glob = str(dataset / "agent_sessions" / "*.parquet").replace("'", "''")
    columns = {
        row[0]
        for row in connection.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{session_glob}')"
        ).fetchall()
    }
    has_index = "session_index" in columns
    rows = connection.execute(
        f"""
        SELECT
            id,
            task.id,
            created_at,
            prompt,
            log_found,
            event.type,
            error,
            {"session_index" if has_index else "NULL"}
        FROM read_parquet('{session_glob}')
        """
    ).fetchall()
    grouped: dict[str, list[tuple]] = defaultdict(list)
    for row in rows:
        grouped[row[1]].append(row)
    sessions: dict[str, Session] = {}
    for group in grouped.values():
        if has_index:
            group.sort(key=lambda row: (row[7], row[0]))
        else:
            group.sort(key=lambda row: (row[2], row[0]))
        previous_id = None
        for row in group:
            prompt = row[3] if isinstance(row[3], str) and row[3] != "" else None
            error = row[6] if isinstance(row[6], str) and row[6] != "" else None
            sessions[row[0]] = Session(row[0], prompt, bool(row[4]), row[5], error, previous_id)
            previous_id = row[0]
    print("Indexing session logs", flush=True)
    files_for_session: dict[str, list[str]] = defaultdict(list)
    log_paths = sorted((dataset / "agent_session_logs").glob("part_*.parquet"))
    for index, path in enumerate(log_paths, 1):
        escaped = str(path).replace("'", "''")
        found = connection.execute(
            f"SELECT DISTINCT session.id FROM read_parquet('{escaped}')"
        ).fetchall()
        for (session_id,) in found:
            files_for_session[session_id].append(path.name)
        print(f"  {path.name} ({index}/{len(log_paths)}): {len(found)} sessions", flush=True)
    candidates = sorted(
        session.id
        for session in sessions.values()
        if session.event_type not in excluded
    )
    order = candidates.copy()
    random.Random(seed).shuffle(order)
    user_texts: dict[str, list[str]] = {}
    assistant_texts: dict[str, str] = {}
    fetched_user: set[str] = set()
    fetched_assistant: set[str] = set()

    def load_slice(session_ids: list[str]) -> None:
        needed, assistant_ids = log_targets(session_ids, sessions)
        to_read = {session_id for session_id in needed if session_id not in fetched_user}
        to_read.update(session_id for session_id in assistant_ids if session_id not in fetched_assistant)
        if not to_read:
            return
        print(f"Reading logs for {len(to_read)} sessions", flush=True)
        files: dict[str, list[str]] = defaultdict(list)
        for session_id in to_read:
            for name in files_for_session.get(session_id, []):
                files[name].append(session_id)
        user_found: dict[str, list[tuple[int, str]]] = defaultdict(list)
        assistant_found: dict[str, list[tuple[int, str]]] = defaultdict(list)
        log_dir = dataset / "agent_session_logs"
        for name, ids in files.items():
            connection.execute("CREATE OR REPLACE TEMP TABLE needed (id VARCHAR)")
            connection.executemany(
                "INSERT INTO needed VALUES (?)",
                [(session_id,) for session_id in ids],
            )
            escaped = str(log_dir / name).replace("'", "''")
            for session_id, entry_index, text in connection.execute(
                f"""
                SELECT session.id, entry_index,
                       array_to_string(
                           list_filter(
                               list_transform(data.content, x -> x.text),
                               x -> x IS NOT NULL
                           ),
                           chr(10)
                       )
                FROM read_parquet('{escaped}')
                WHERE session.id IN (SELECT id FROM needed)
                  AND parsed
                  AND data.role = 'user'
                ORDER BY session.id, entry_index
                """
            ).fetchall():
                user_found[session_id].append((entry_index, text or ""))
            assistant_in_file = [session_id for session_id in ids if session_id in assistant_ids]
            if assistant_in_file:
                connection.execute("CREATE OR REPLACE TEMP TABLE assistant_needed (id VARCHAR)")
                connection.executemany(
                    "INSERT INTO assistant_needed VALUES (?)",
                    [(session_id,) for session_id in assistant_in_file],
                )
                for session_id, entry_index, text in connection.execute(
                    f"""
                    SELECT session.id, entry_index,
                           array_to_string(
                               list_filter(
                                   list_transform(data.choices, c -> c.delta.content),
                                   x -> x IS NOT NULL
                               ),
                               ''
                           )
                    FROM read_parquet('{escaped}')
                    WHERE session.id IN (SELECT id FROM assistant_needed)
                      AND parsed
                      AND len(list_filter(data.choices, c -> c.finish_reason = 'stop')) > 0
                    ORDER BY session.id, entry_index
                    """
                ).fetchall():
                    if text:
                        assistant_found[session_id].append((entry_index, text))
            print(f"  {name}: {len(ids)} sessions", flush=True)
        for session_id in to_read:
            if session_id not in fetched_user:
                user_texts[session_id] = [
                    text for _, text in sorted(user_found.get(session_id, []))
                ]
                fetched_user.add(session_id)
        for session_id, entries in assistant_found.items():
            for _, text in sorted(entries, key=lambda item: item[0], reverse=True):
                if "<pr_title>" in text or "<pr_description>" in text:
                    continue
                assistant_texts[session_id] = text
                break
        for session_id in assistant_ids:
            if session_id in to_read:
                fetched_assistant.add(session_id)

    end = min(len(order), sample_size + max(80, sample_size // 3))
    load_slice(order[:end])
    sampled = first_eligible(order[:end], sample_size, sessions, user_texts)
    while sampled is None:
        nxt = min(len(order), end + max(80, sample_size // 3))
        if nxt == end:
            raise SystemExit(f"only fewer than {sample_size} eligible sessions")
        extra = order[end:nxt]
        end = nxt
        print(f"Extending draw by {len(extra)} sessions", flush=True)
        load_slice(extra)
        sampled = first_eligible(order[:end], sample_size, sessions, user_texts)
    return sampled, sessions, user_texts, assistant_texts


def write_sample(
    output: Path,
    sampled_ids: list[str],
    sessions: dict[str, Session],
    user_texts: dict[str, list[str]],
    assistant_texts: dict[str, str],
    seed: int,
) -> None:
    md_dir = output / "md"
    html_dir = output / "html"
    if output.exists():
        shutil.rmtree(output)
    md_dir.mkdir(parents=True)
    html_dir.mkdir(parents=True)

    links: list[str] = []
    sources = {"prompt": 0, "problem_statement": 0, "both": 0}
    for session_id in sampled_ids:
        session = sessions[session_id]
        current, found_using = build_user_turn(
            user_texts.get(session_id, []),
            session.prompt,
            CURRENT_LIMIT,
        )
        previous = sessions.get(session.previous_id) if session.previous_id else None
        previous_user = None
        previous_assistant = None
        if previous is not None:
            previous_user, _ = build_user_turn(
                user_texts.get(previous.id, []),
                previous.prompt,
                PREVIOUS_LIMIT,
            )
            previous_assistant = build_assistant_turn(
                previous.error,
                assistant_texts.get(previous.id),
            )
        if current is None or found_using is None:
            raise SystemExit(f"session {session_id} has no prompt text")
        message = build_classification_message(current, previous_user, previous_assistant)
        sources[found_using] += 1
        (md_dir / f"{session_id}.md").write_text(message + "\n", encoding="utf-8")
        (html_dir / f"{session_id}.html").write_text(prompt_html(session_id, message), encoding="utf-8")
        links.append(f'<li><a href="{html.escape(session_id)}.html">{html.escape(session_id)}</a></li>')

    (html_dir / "index.html").write_text(
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        "<title>Sample</title>\n"
        "</head>\n"
        "<body>\n"
        f"<p>{len(sampled_ids)} sessions, seed {seed}.</p>\n"
        "<ul>\n"
        + "\n".join(links)
        + "\n</ul>\n"
        "</body>\n"
        "</html>\n",
        encoding="utf-8",
    )
    (output / "sample.json").write_text(
        json.dumps(
            {
                "seed": seed,
                "sample_size": len(sampled_ids),
                "python": sys.version,
                "session_ids": sampled_ids,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {len(sampled_ids)} prompts to {output}: "
        f"{sources['both']} both, "
        f"{sources['prompt']} prompt, "
        f"{sources['problem_statement']} problem statement",
        flush=True,
    )


if __name__ == "__main__":
    sampled_ids, sessions, user_texts, assistant_texts = draw_sample(DATASET, SEED, SAMPLE_SIZE)
    write_sample(OUTPUT, sampled_ids, sessions, user_texts, assistant_texts, SEED)
