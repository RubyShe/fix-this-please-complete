import asyncio
import datetime as dt
import time
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.live import Live
from rich.table import Table
from rich.text import Text

from classification.openai import Limit, OpenAIAPI


class EMA:
    def __init__(self, smoothing: float) -> None:
        self.smoothing = smoothing
        self.last = 0.0
        self.calls = 0

    def __call__(self, value: float | None = None) -> float:
        if value is None:
            return self.last
        if self.calls:
            self.last = self.smoothing * value + (1 - self.smoothing) * self.last
        else:
            self.last = value
        self.calls += 1
        return self.last


class ProgressRate:
    mininterval = 1.0
    smoothing = 0.1

    def __init__(self, n: int, at: float) -> None:
        self.n = n
        self.at = at
        self.dn = EMA(self.smoothing)
        self.dt = EMA(self.smoothing)

    def observe(self, n: int, at: float) -> float | None:
        if n < self.n:
            self.n = n
            self.at = at
            self.dn = EMA(self.smoothing)
            self.dt = EMA(self.smoothing)
            return None
        dn = n - self.n
        elapsed = at - self.at
        if dn > 0 and elapsed >= self.mininterval:
            self.dn(float(dn))
            self.dt(elapsed)
            self.n = n
            self.at = at
        if not self.dt.calls:
            return None
        return self.dn() / self.dt()


def format_timedelta(delta: dt.timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def format_money(value: float) -> str:
    if value == 0 or abs(value) >= 1:
        return f"${value:,.2f}"
    if abs(value) >= 0.01:
        return f"${value:,.4f}"
    return f"${value:.6f}"


def bar(current: int, total: int, width: int = 16) -> str:
    if total <= 0 or current <= 0:
        filled = 0
    elif current >= total:
        filled = width
    else:
        filled = min(width - 1, max(1, round(width * current / total)))
    return f"[{'█' * filled}{'░' * (width - filled)}]"


class Dashboard:
    def __init__(
        self,
        api: OpenAIAPI,
        finished: int,
        errors: int,
        input_tokens: int,
        output_tokens: int,
        cost: float,
        pending: int,
    ) -> None:
        self.api = api
        self.finished = finished
        self.errors = errors
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.cost = cost
        self.pending = pending
        self.rate = ProgressRate(finished + errors, time.monotonic())
        self.console = Console()

    def add(self, record: dict[str, Any]) -> None:
        self.finished += 1
        self.pending -= 1
        self.input_tokens += int(record.get("input_tokens") or 0)
        self.output_tokens += int(record.get("output_tokens") or 0)
        self.cost += float(record.get("cost") or 0)

    def fail(self) -> None:
        self.errors += 1
        self.pending -= 1

    async def run(self) -> None:
        with Live(self.render(), console=self.console, refresh_per_second=4) as live:
            try:
                while True:
                    live.update(self.render())
                    await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                live.update(self.render())
                raise

    def render(self) -> Group:
        return Group(self.prompt_table(), self.limit_table())

    def prompt_table(self) -> Group:
        now = time.monotonic()
        per_second = self.rate.observe(self.finished + self.errors, now)
        remaining = max(0, self.pending)
        rate, eta = self.rate_and_eta(per_second, remaining)
        if self.finished > 0:
            input_each = f"{self.input_tokens / self.finished:,.1f}"
            output_each = f"{self.output_tokens / self.finished:,.1f}"
            cost_each = format_money(self.cost / self.finished)
            projected = format_money(self.cost / self.finished * (self.finished + self.pending))
        else:
            input_each = "—"
            output_each = "—"
            cost_each = "—"
            projected = "—"
        progress = Table(
            title="prompts",
            expand=True,
            padding=(0, 1),
            pad_edge=False,
            box=box.SIMPLE_HEAD,
        )
        progress.add_column("progress", no_wrap=True, ratio=1)
        progress.add_column("errors", justify="right", no_wrap=True)
        progress.add_column("it/s", justify="right", no_wrap=True)
        progress.add_column("eta", justify="right", no_wrap=True)
        counted = self.finished + self.pending
        count = f"{self.finished:,}/{counted:,}"
        errors = Text(f"{self.errors:,}")
        if self.errors:
            errors.stylize("red")
        progress.add_row(f"{bar(self.finished, counted, width=10)} {count}", errors, rate, eta)
        tokens = Table(
            expand=True,
            padding=(0, 1),
            pad_edge=False,
            box=box.SIMPLE_HEAD,
        )
        tokens.add_column("input", justify="right", no_wrap=True)
        tokens.add_column("input/prompt", justify="right", no_wrap=True)
        tokens.add_column("output", justify="right", no_wrap=True)
        tokens.add_column("output/prompt", justify="right", no_wrap=True)
        tokens.add_row(
            f"{self.input_tokens:,}",
            input_each,
            f"{self.output_tokens:,}",
            output_each,
        )
        cost = Table(
            expand=True,
            padding=(0, 1),
            pad_edge=False,
            box=box.SIMPLE_HEAD,
        )
        cost.add_column("cost", justify="right", no_wrap=True)
        cost.add_column("cost/prompt", justify="right", no_wrap=True)
        cost.add_column("projected", justify="right", no_wrap=True)
        cost.add_row(format_money(self.cost), cost_each, projected)
        return Group(progress, tokens, cost)

    def limit_table(self) -> Table:
        table = Table(
            title="openai",
            expand=True,
            padding=(0, 1),
            pad_edge=False,
            box=box.SIMPLE_HEAD,
        )
        table.add_column("limit", no_wrap=True, ratio=1)
        table.add_column("remaining", no_wrap=True)
        table.add_column("wait", justify="right", no_wrap=True)
        now = time.monotonic()
        for name, limit in (("requests", self.api.request_limit), ("tokens", self.api.token_limit)):
            table.add_row(*self.limit_row(name, limit, now))
        return table

    def limit_row(self, name: str, limit: Limit, now: float) -> tuple[Text, Text, Text]:
        label = name
        if limit.ceiling is not None:
            label = f"{name} {limit.ceiling:,}/{limit.maximum:,}"
        remaining = f"{bar(max(limit.remaining, 0), limit.limit)} {limit.remaining:,}/{limit.limit:,}"
        wait = limit.reset_at - now if limit.remaining <= 0 and limit.reset_at > now else 0.0
        if wait > 0:
            shown = format_timedelta(dt.timedelta(seconds=wait))
        else:
            shown = f"{'—':>8}"
        cells = (Text(label), Text(remaining.replace(" ", "\u00a0")), Text(shown))
        if limit.remaining <= 0:
            for cell in cells:
                cell.stylize("red")
        return cells

    def rate_and_eta(self, per_second: float | None, remaining: int) -> tuple[str, str]:
        if per_second and remaining > 0:
            seconds = remaining / per_second
            if seconds <= dt.timedelta.max.total_seconds():
                eta = format_timedelta(dt.timedelta(seconds=seconds))
            else:
                eta = f"{'—':>8}"
        elif remaining == 0:
            eta = format_timedelta(dt.timedelta(0))
        else:
            eta = f"{'—':>8}"
        return f"{per_second or 0:5.2f}", eta
