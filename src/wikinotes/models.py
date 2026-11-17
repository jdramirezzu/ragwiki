"""Talking to a language model: the port, the metering wrapper and the OpenAI-compatible adapter."""

import json
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Reply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0


DEFAULT_CONTEXT_TOKENS = 32_000


def estimate_tokens(text: str) -> int:
    """A rough token count: about four characters per token.

    Good enough to split long sources and to forecast cost without depending on any
    provider's tokenizer. Real counts come back from the provider after each call.
    """
    return (len(text) + 3) // 4


class Model(Protocol):
    def complete(self, system: str, user: str) -> Reply: ...


class ConfigError(Exception):
    """Raised when the model is not configured."""


class BudgetExceeded(Exception):
    """Raised when the spending cap has been reached."""


class ModelError(Exception):
    """Raised when the provider cannot be reached or rejects the request."""


class MeteredModel:
    """Wraps a model to record tokens, time and price of every call and enforce a cap.

    Prices are in USD per million tokens. The log never stores prompts or replies, because
    they contain the user's notes.
    """

    def __init__(
        self,
        inner: Model,
        log_path: Path,
        price_input: float = 0.0,
        price_output: float = 0.0,
        max_usd: float | None = None,
    ) -> None:
        self.inner = inner
        self.log_path = Path(log_path)
        self.price_input = price_input
        self.price_output = price_output
        self.max_usd = max_usd
        self.calls = 0
        self.spent_usd = 0.0

    def complete(self, system: str, user: str) -> Reply:
        if self.max_usd is not None and self.spent_usd >= self.max_usd:
            raise BudgetExceeded(
                f"Spending cap reached: ${self.spent_usd:.4f} of ${self.max_usd:.4f}. "
                "Raise WIKINOTES_MAX_USD to continue."
            )
        start = time.monotonic()
        reply = self.inner.complete(system, user)
        usd = (
            reply.input_tokens * self.price_input + reply.output_tokens * self.price_output
        ) / 1_000_000
        self.calls += 1
        self.spent_usd += usd
        entry = {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "seconds": round(time.monotonic() - start, 3),
            "input_tokens": reply.input_tokens,
            "output_tokens": reply.output_tokens,
            "usd": round(usd, 6),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry) + "\n")
        return reply


class OpenAICompatibleModel:
    """Any endpoint that speaks the OpenAI chat API: hosted providers or a local server."""

    def __init__(self, model: str, base_url: str | None = None, api_key: str | None = None) -> None:
        from openai import OpenAI

        self.model = model
        # Local servers ignore the key, but the SDK refuses to start without one.
        self.client = OpenAI(base_url=base_url, api_key=api_key or "not-needed")

    def complete(self, system: str, user: str) -> Reply:
        from openai import OpenAIError

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except OpenAIError as error:
            raise ModelError(f"The model request failed: {error}") from error
        usage = response.usage
        return Reply(
            text=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
        )


def _env_float(name: str) -> float | None:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except ValueError as error:
        raise ConfigError(f"{name} must be a number, got '{raw}'") from error


def context_tokens_from_env() -> int:
    """The model's context window, which decides when a long source is split into parts."""
    value = _env_float("WIKINOTES_CONTEXT_TOKENS")
    if value is None:
        return DEFAULT_CONTEXT_TOKENS
    if value < 1:
        raise ConfigError(f"WIKINOTES_CONTEXT_TOKENS must be a positive number, got '{value:g}'")
    return int(value)


def model_from_env() -> OpenAICompatibleModel:
    name = os.environ.get("WIKINOTES_MODEL")
    if not name:
        raise ConfigError(
            "No model configured. Set WIKINOTES_MODEL (and WIKINOTES_BASE_URL and "
            "WIKINOTES_API_KEY for your provider). See the README for examples."
        )
    return OpenAICompatibleModel(
        model=name,
        base_url=os.environ.get("WIKINOTES_BASE_URL") or None,
        api_key=os.environ.get("WIKINOTES_API_KEY") or None,
    )


def metered_from_env(log_path: Path) -> MeteredModel:
    return MeteredModel(
        model_from_env(),
        log_path,
        price_input=_env_float("WIKINOTES_PRICE_INPUT") or 0.0,
        price_output=_env_float("WIKINOTES_PRICE_OUTPUT") or 0.0,
        max_usd=_env_float("WIKINOTES_MAX_USD"),
    )


def extract_json(text: str) -> dict:
    """Read the JSON object in a model reply, tolerating code fences and surrounding prose."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("the reply contains no JSON object")
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise ValueError(f"the reply is not valid JSON ({error.msg})") from error
    if not isinstance(data, dict):
        raise ValueError("the reply must be a JSON object")
    return data
