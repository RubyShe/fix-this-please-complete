import re

from agentlogs.schema import AgentSession, AgentSessionLogEntry

CURRENT_LIMIT = 16_000
PREVIOUS_LIMIT = 8_000
ASSISTANT_LIMIT = 2_000
LABEL_ATTEMPTS = 1
STATEMENT_OPEN = "<problem_statement>"
STATEMENT_CLOSE = "</problem_statement>"
STRIP_TAGS = {"memories", "repository_memories", "reminder", "replying_to_comments"}
OPEN_TAG = re.compile(r"<([A-Za-z_][A-Za-z0-9_]*)>")
STEP_HEAD = re.compile(r"^\s*#{0,3}\s*Steps to Follow\s*$")
STEP_LINE = re.compile(r"^\s*\d+\.\s")
STEP_CONTINUATION = re.compile(r"^\s+\S")


def build_prompt(
    session: AgentSession,
    session_log: list[AgentSessionLogEntry] | None,
    previous_session: AgentSession | None,
    previous_session_log: list[AgentSessionLogEntry] | None,
) -> str | None:
    """Build the text for one session.

    `direct` rows (`review-request`) skip this text. `missing` rows have neither
    source in step 1. `error` rows had text, and the model call failed. `labels`
    and `reasoning` are null for `missing` and `error`.
    """
    # 1. Read the current session's prompt when that string is non-empty. It is
    # often unset. Walk the log in entry_index order and take the first user
    # message that contains a <problem_statement>.
    prompt = session["prompt"] if isinstance(session["prompt"], str) and session["prompt"] != "" else None
    # 2. If the statement body repeats the prompt, ignoring case and whitespace,
    # drop the prompt. Wrap what remains in <current>, as <request>, <prompt>,
    # or both.
    # 3. Clean the log message. Remove closed memories, repository_memories,
    # reminder, and replying_to_comments tags. After the statement, also remove
    # repository_context and a "Steps to Follow" numbered list. Cut the combined
    # turn to 16,000 characters: drop <comment_old> from the front, then keep
    # the first 30% of that budget and the tail.
    current, source = build_user_turn(user_messages(session_log), prompt, CURRENT_LIMIT)
    if current is None or source is None:
        return None
    previous_user = None
    previous_assistant = None
    if previous_session is not None:
        # 4. If this session is not the first in its task, the previous session
        # is the one with the preceding session_index. Build its user text the
        # same way, with an 8,000-character budget, and wrap it in <prev_user>.
        previous_prompt = previous_session["prompt"]
        if not isinstance(previous_prompt, str) or previous_prompt == "":
            previous_prompt = None
        previous_texts = user_messages(previous_session_log)
        previous_reply = last_assistant_reply(previous_session_log)
        previous_error = previous_session["error"]
        if not isinstance(previous_error, str) or previous_error == "":
            previous_error = None
        previous_user, _found = build_user_turn(previous_texts, previous_prompt, PREVIOUS_LIMIT)
        # 5. For that previous session, use its error string when one is set.
        # Otherwise use the last assistant reply in its log. Cut that text to
        # 2,000 characters and wrap it in <prev_assistant>.
        previous_assistant = build_assistant_turn(previous_error, previous_reply)
    return build_classification_message(current, previous_user, previous_assistant)


def user_messages(entries: list[AgentSessionLogEntry] | None) -> list[str]:
    """Walk the session log in `entry_index` order and return each user message."""
    if not entries:
        return []
    texts: list[str] = []
    for entry in sorted(entries, key=lambda item: item["entry_index"]):
        data = entry["data"]
        if data is None or data.get("role") != "user":
            continue
        parts = [part.get("text") for part in data.get("content") or [] if part.get("text")]
        texts.append("\n".join(parts))
    return texts


def build_user_turn(texts: list[str], prompt: str | None, limit: int) -> tuple[str | None, str | None]:
    """Take the first user message that contains a `<problem_statement>`.

    If the statement body repeats the prompt, ignoring case and whitespace, drop
    the prompt. Clean the log message and wrap what remains as `<request>`,
    `<prompt>`, or both. Cut the combined turn to `limit` characters: drop
    `<comment_old>` from the front, then keep the first 30% of that budget and
    the tail.
    """
    message = None
    for text in texts:
        close_at = text.find(STATEMENT_CLOSE)
        if close_at == -1:
            continue
        if STATEMENT_OPEN not in text[:close_at]:
            continue
        message = text
        break
    text, found_using = select_text(message, prompt)
    if text is None:
        return None, None
    return fit_budget(text, limit), found_using


def select_text(message: str | None, prompt: str | None) -> tuple[str | None, str]:
    """If the statement body repeats the prompt, ignoring case and whitespace, drop the prompt.

    Wrap what remains as `<request>`, `<prompt>`, or both.
    """
    if (
        message is not None
        and prompt is not None
        and statement_matches_prompt(message, prompt)
    ):
        prompt = None
    stripped = strip_paired_message(message) if message is not None else None
    if stripped and prompt:
        return (
            f"<request>\n{stripped}\n</request>\n<prompt>\n{prompt}\n</prompt>",
            "both",
        )
    if stripped:
        return f"<request>\n{stripped}\n</request>", "problem_statement"
    if prompt:
        return f"<prompt>\n{prompt}\n</prompt>", "prompt"
    return None, "prompt"


def statement_matches_prompt(message: str, prompt: str) -> bool:
    """Whether the statement body repeats the prompt, ignoring case and whitespace."""
    statement = " ".join(get_statement_body(message).lower().split())
    return statement == " ".join(prompt.lower().split())


def get_statement_body(message: str) -> str:
    close_at = message.find(STATEMENT_CLOSE)
    open_at = message.rfind(STATEMENT_OPEN, 0, close_at)
    return message[open_at + len(STATEMENT_OPEN):close_at]


def strip_paired_message(message: str) -> str:
    """Clean the log message.

    Remove closed `memories`, `repository_memories`, `reminder`, and
    `replying_to_comments` tags. After the statement, also remove
    `repository_context` and a "Steps to Follow" numbered list.
    """
    close_at = message.find(STATEMENT_CLOSE)
    open_at = message.rfind(STATEMENT_OPEN, 0, close_at)
    prefix = strip_region(message[:open_at], STRIP_TAGS, steps=False)
    body = strip_region(
        message[open_at + len(STATEMENT_OPEN):close_at],
        STRIP_TAGS,
        steps=False,
    )
    suffix = strip_region(
        message[close_at + len(STATEMENT_CLOSE):],
        STRIP_TAGS | {"repository_context"},
        steps=True,
    )
    return f"{prefix}{STATEMENT_OPEN}{body}{STATEMENT_CLOSE}{suffix}"


def strip_region(text: str, names: set[str], steps: bool) -> str:
    text = remove_closed_tags(text, names)
    if not steps:
        return text
    pieces: list[str] = []
    for kind, chunk in parse_prose_gaps(text):
        if kind == "tag":
            pieces.append(chunk)
            continue
        if chunk.lstrip().startswith("The following are recent memories"):
            continue
        pieces.append(strip_numbered_steps(chunk))
    return "".join(pieces)


def remove_closed_tags(text: str, names: set[str]) -> str:
    pieces: list[str] = []
    cursor = 0
    for start, end in find_closed_elements(text, names):
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


def find_closed_elements(text: str, names: set[str]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    while cursor < len(text):
        match = OPEN_TAG.search(text, cursor)
        if match is None:
            break
        name = match.group(1)
        open_tag = match.group(0)
        if name not in names:
            cursor = match.end()
            continue
        close_tag = f"</{name}>"
        close_at = find_matching_close(text, match.start(), open_tag, close_tag)
        if close_at is None:
            cursor = match.end()
            continue
        end = close_at + len(close_tag)
        spans.append((match.start(), end))
        cursor = end
    return spans


def find_matching_close(text: str, open_at: int, open_tag: str, close_tag: str) -> int | None:
    depth = 1
    scan = open_at + len(open_tag)
    while scan < len(text):
        next_open = text.find(open_tag, scan)
        next_close = text.find(close_tag, scan)
        if next_close == -1:
            return None
        if next_open != -1 and next_open < next_close:
            depth += 1
            scan = next_open + len(open_tag)
            continue
        depth -= 1
        if depth == 0:
            return next_close
        scan = next_close + len(close_tag)
    return None


def parse_prose_gaps(text: str) -> list[tuple[str, str]]:
    pieces: list[tuple[str, str]] = []
    prose_at = 0
    cursor = 0
    while cursor < len(text):
        match = OPEN_TAG.search(text, cursor)
        if match is None:
            break
        open_tag = match.group(0)
        close_tag = f"</{match.group(1)}>"
        close_at = find_matching_close(text, match.start(), open_tag, close_tag)
        if close_at is None:
            cursor = match.end()
            continue
        end = close_at + len(close_tag)
        pieces.append(("prose", text[prose_at:match.start()]))
        pieces.append(("tag", text[match.start():end]))
        prose_at = end
        cursor = end
    pieces.append(("prose", text[prose_at:]))
    return pieces


def strip_numbered_steps(prose: str) -> str:
    """Remove a "Steps to Follow" numbered list."""
    def continues_step(line: str) -> bool:
        return bool(
            STEP_HEAD.match(line)
            or STEP_LINE.match(line)
            or STEP_CONTINUATION.match(line)
        )

    lines = prose.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not STEP_HEAD.match(line) and not STEP_LINE.match(line):
            kept.append(line)
            index += 1
            continue
        index += 1
        while index < len(lines):
            if lines[index].strip() == "":
                look = index + 1
                while look < len(lines) and lines[look].strip() == "":
                    look += 1
                if look < len(lines) and continues_step(lines[look]):
                    index = look
                    continue
                break
            if continues_step(lines[index]):
                index += 1
                continue
            break
    return "\n".join(kept)


def fit_budget(text: str, limit: int) -> str:
    """Cut `text` to `limit` characters.

    Drop `<comment_old>` from the front, then keep the first 30% of that budget
    and the tail.
    """
    return keep_head_and_tail(drop_old_comments(text, limit), limit)


def drop_old_comments(text: str, limit: int) -> str:
    """Drop `<comment_old>` from the front until `text` fits in `limit` characters."""
    extra = len(text) - limit
    if extra <= 0:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end in find_closed_elements(text, {"comment_old"}):
        if extra <= 0:
            break
        pieces.append(text[cursor:start])
        take = min(extra, end - start)
        cursor = start + take
        extra -= take
    pieces.append(text[cursor:])
    return "".join(pieces)


def keep_head_and_tail(text: str, limit: int) -> str:
    """Keep the first 30% of `limit` and the tail."""
    if len(text) <= limit:
        return text
    head = limit * 3 // 10
    return text[:head] + text[-(limit - head):]


def last_assistant_reply(entries: list[AgentSessionLogEntry] | None) -> str | None:
    """Last assistant reply in the log.

    `delta.content` from a choice whose `finish_reason` is `stop`, skipping
    replies that contain `<pr_title>` or `<pr_description>`.
    """
    if not entries:
        return None
    assistant = None
    for entry in sorted(entries, key=lambda item: item["entry_index"]):
        data = entry["data"]
        if data is None:
            continue
        stopped = False
        reply: list[str] = []
        for choice in data.get("choices") or []:
            if choice.get("finish_reason") == "stop":
                stopped = True
            content = (choice.get("delta") or {}).get("content")
            if content:
                reply.append(content)
        if not stopped or not reply:
            continue
        text = "".join(reply)
        if "<pr_title>" in text or "<pr_description>" in text:
            continue
        assistant = text
    return assistant


def build_assistant_turn(error: str | None, raw_text: str | None) -> str | None:
    """Use the session `error` string when one is set. Otherwise use the last assistant reply.

    Cut that text to 2,000 characters, keeping the first 30% of that budget and
    the tail.
    """
    text = error if error else raw_text
    if not text:
        return None
    if error is None and ("<pr_title>" in text or "<pr_description>" in text):
        return None
    return keep_head_and_tail(text, ASSISTANT_LIMIT)


def build_classification_message(
    current: str,
    previous_user: str | None,
    previous_assistant: str | None,
) -> str:
    """Wrap the current turn in `<current>`.

    When present, wrap the previous user text in `<prev_user>` and the previous
    agent reply in `<prev_assistant>`.
    """
    blocks: list[str] = []
    if previous_user is not None:
        blocks.append(f"<prev_user>\n{previous_user}\n</prev_user>")
    if previous_assistant:
        blocks.append(f"<prev_assistant>\n{previous_assistant}\n</prev_assistant>")
    blocks.append(f"<current>\n{current}\n</current>")
    return "\n".join(blocks)


def get_session_prompt(payload: dict) -> str | None:
    prompt = payload.get("prompt")
    if isinstance(prompt, str) and prompt != "":
        return prompt
    return None
