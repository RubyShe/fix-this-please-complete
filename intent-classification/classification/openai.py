import asyncio
import math
import random
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

API_URL = "https://api.openai.com/v1/chat/completions"
MODEL = "gpt-6-luna"
MAX_OUTPUT_TOKENS = 4096
REQUESTS_PER_MINUTE = 5_000
TOKENS_PER_MINUTE = 2_000_000
TIER_PRICES = {
    "default": (0.10, 0.50),
    "flex": (0.05, 0.25),
}
RAMP_INTERVAL = 15 * 60
RAMP_FACTOR = 1.5
RESET_PARTS = re.compile(r"(\d+(?:\.\d+)?)(ms|s|m|h)")
BILLING_CODES = {
    "credit_balance_exhausted",
    "organization_spend_limit_exceeded",
    "project_spend_limit_exceeded",
    "organization_usage_limit_exceeded",
    "insufficient_quota",
}
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 520}


class APIError(Exception):
    pass


@dataclass(frozen=True)
class OpenAICompletion:
    input_tokens: int
    output_tokens: int
    model: str
    cost: float
    response: dict[str, Any]


def parse_reset(value: str) -> float:
    seconds = 0.0
    for amount, unit in RESET_PARTS.findall(value):
        seconds += float(amount) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return seconds


def get_text_length(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(get_text_length(part) for part in value)
    if isinstance(value, dict):
        text = value.get("text")
        return len(text) if isinstance(text, str) else 0
    return 0


class Limit:
    def __init__(self, per_minute: int, ramp: bool = False):
        self.limit = per_minute
        self.remaining = per_minute
        self.in_flight = 0
        self.reset_at = 0.0
        self.configured = per_minute
        self.maximum = per_minute
        self.ramp = ramp
        self.ceiling: int | None = None
        self.ramp_at = 0.0

    def refill(self) -> None:
        if self.remaining == 0 and time.monotonic() >= self.reset_at:
            self.remaining = self.limit

    def can_take(self, cost: int) -> bool:
        self.refill()

        return self.remaining >= cost

    def wait_seconds(self) -> float:
        self.refill()

        if self.remaining == 0:
            return max(self.reset_at - time.monotonic(), 0)

        return 0

    def take(self, cost: int) -> None:
        self.remaining -= cost
        self.in_flight += cost

        if self.remaining == 0 and time.monotonic() >= self.reset_at:
            self.reset_at = time.monotonic() + 60

    def release(self, cost: int) -> None:
        self.in_flight -= cost
        self.remaining += cost

    def set_limit(self, value: int) -> None:
        if not self.ramp:
            self.limit = value
            return

        self.maximum = min(self.configured, value)
        self.grow_ramp()
        self.limit = value if self.ceiling is None else min(value, self.ceiling)

    def set_remaining(self, value: int) -> None:
        if self.ceiling is not None:
            self.grow_ramp()
            value = min(value, self.ceiling)

        self.remaining = value

    def start_ramp(self) -> None:
        used = max(0, self.limit - max(self.remaining, 0))
        self.ceiling = min(used if used > 0 else max(1, self.limit // 2), self.maximum)
        self.ramp_at = time.monotonic() + RAMP_INTERVAL
        self.limit = min(self.limit, self.ceiling)
        self.remaining = min(self.remaining, self.ceiling)

    def grow_ramp(self) -> None:
        if not self.ramp or self.ceiling is None:
            return

        now = time.monotonic()
        while now >= self.ramp_at and self.ceiling < self.maximum:
            grown = int(self.ceiling * RAMP_FACTOR)
            if grown <= self.ceiling:
                grown = self.ceiling + 1
            self.ceiling = min(self.maximum, grown)
            self.ramp_at += RAMP_INTERVAL

        self.limit = min(self.limit, self.ceiling)
        self.remaining = min(self.remaining, self.ceiling)


class OpenAIAPI:
    def __init__(self, api_key: str, connections: int = 100):
        self.api_key = api_key
        self.request_limit = Limit(REQUESTS_PER_MINUTE)
        self.token_limit = Limit(TOKENS_PER_MINUTE, ramp=True)
        self.client = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(
                max_connections=connections,
                max_keepalive_connections=connections,
            ),
            timeout=httpx.Timeout(connect=10.0, read=900.0, write=10.0, pool=10.0),
        )
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self.client.aclose()

    def get_message_length(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for message in messages:
            total += get_text_length(message.get("role"))
            total += get_text_length(message.get("content"))
            total += get_text_length(message.get("name"))
        return total

    async def complete(
        self,
        messages: list[dict[str, Any]],
        response_format: dict[str, Any] | None = None,
        service_tier: str | None = None,
    ) -> OpenAICompletion:
        reserved = math.ceil(self.get_message_length(messages) / 4) + MAX_OUTPUT_TOKENS

        body: dict[str, Any] = {
            "model": MODEL,
            "messages": messages,
            "max_completion_tokens": MAX_OUTPUT_TOKENS,
        }
        if response_format is not None:
            body["response_format"] = response_format
        if service_tier is not None:
            if service_tier not in TIER_PRICES:
                raise APIError(f"unknown service tier {service_tier}")
            body["service_tier"] = service_tier

        last_error = "request failed"
        for attempt in range(3):
            await self.claim_budget(reserved)

            try:
                response = await self.client.post(
                    API_URL,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=body,
                )
            except httpx.HTTPError as error:
                last_error = str(error)
                await self.release_budget(reserved)
                await asyncio.sleep(min(2 ** attempt, 30) + random.uniform(0, 0.25))
                continue

            await self.release_budget(reserved, response.headers)

            if response.status_code == 200:
                payload = response.json()
                usage = payload["usage"]
                tier = payload.get("service_tier") or service_tier or "default"
                if tier not in TIER_PRICES:
                    raise APIError(f"unknown service tier {tier}")
                input_price, output_price = TIER_PRICES[tier]
                cost = (
                    usage["prompt_tokens"] * input_price
                    + usage["completion_tokens"] * output_price
                ) / 1_000_000
                return OpenAICompletion(
                    input_tokens=usage["prompt_tokens"],
                    output_tokens=usage["completion_tokens"],
                    model=payload["model"],
                    cost=cost,
                    response=payload,
                )

            try:
                error = response.json()["error"]
            except (KeyError, TypeError, ValueError):
                error = None
            if not isinstance(error, dict):
                code = ""
                message = f"Request failed with status code {response.status_code}"
                last_error = message
                if response.status_code not in RETRYABLE_STATUS:
                    raise APIError(f"{message}: {response.text}")
            else:
                code = error.get("code") or ""
                message = error.get("message") or response.text
                last_error = message
                if response.status_code in (400, 401, 403, 404, 422):
                    raise APIError(message)
                if response.status_code == 429 and (
                    code in BILLING_CODES or error.get("type") == "insufficient_quota"
                ):
                    raise APIError(message)
                if response.status_code not in RETRYABLE_STATUS:
                    raise APIError(
                        f"Request failed with status code {response.status_code}: {response.text}"
                    )

            if code == "slow_down":
                await self.start_ramp()

            retry_after = response.headers.get("retry-after")
            try:
                wait = max(float(retry_after), 0.05)
            except (TypeError, ValueError):
                parsed = parse_reset(retry_after or "")
                wait = parsed if parsed > 0 else min(2 ** attempt, 30)
            await asyncio.sleep(wait + random.uniform(0, 0.25))

        raise APIError(last_error)

    async def claim_budget(self, tokens: int) -> None:
        while True:
            async with self._lock:
                self.token_limit.grow_ramp()
                if self.request_limit.can_take(1) and self.token_limit.can_take(tokens):
                    self.request_limit.take(1)
                    self.token_limit.take(tokens)
                    return
                wait = max(self.request_limit.wait_seconds(), self.token_limit.wait_seconds(), 0.05)
            await asyncio.sleep(wait)

    async def release_budget(self, reserved: int, headers: Mapping[str, str] | None = None) -> None:
        found = {key.lower(): value for key, value in headers.items()} if headers else {}

        async with self._lock:
            self.request_limit.release(1)
            self.token_limit.release(reserved)

            for limit, name in ((self.request_limit, "requests"), (self.token_limit, "tokens")):
                remaining_name = f"x-ratelimit-remaining-{name}"
                if remaining_name not in found:
                    continue

                if f"x-ratelimit-limit-{name}" in found:
                    limit.set_limit(int(found[f"x-ratelimit-limit-{name}"]))

                limit.set_remaining(int(found[remaining_name]) - limit.in_flight)

                reset_name = f"x-ratelimit-reset-{name}"
                if reset_name in found:
                    limit.reset_at = time.monotonic() + parse_reset(found[reset_name])

            if "x-ratelimit-remaining-project-tokens" in found:
                project = int(found["x-ratelimit-remaining-project-tokens"]) - self.token_limit.in_flight
                if project < self.token_limit.remaining:
                    self.token_limit.set_remaining(project)
                    if "x-ratelimit-reset-project-tokens" in found:
                        self.token_limit.reset_at = (
                            time.monotonic()
                            + parse_reset(found["x-ratelimit-reset-project-tokens"])
                        )

    async def start_ramp(self) -> None:
        async with self._lock:
            self.token_limit.start_ramp()
