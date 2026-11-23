"""Talking to a language model: the port, the metering wrapper and the OpenAI-compatible adapter."""

import base64
import json
import os
import re
import time
from collections.abc import Sequence
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


@dataclass(frozen=True)
class Image:
    """A picture sent to the model with a prompt, such as a photo of handwritten notes."""

    media_type: str
    data: bytes


class Model(Protocol):
    """What ragwiki needs from a language model.

    `images` is only passed when a photo has to be transcribed, so a model that never sees
    photos may implement `complete(system, user)` alone.
    """

    def complete(self, system: str, user: str, images: Sequence[Image] = ()) -> Reply: ...


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

    def complete(self, system: str, user: str, images: Sequence[Image] = ()) -> Reply:
        if self.max_usd is not None and self.spent_usd >= self.max_usd:
            raise BudgetExceeded(
                f"Spending cap reached: ${self.spent_usd:.4f} of ${self.max_usd:.4f}. "
                "Raise RAGWIKI_MAX_USD to continue."
            )
        start = time.monotonic()
        if images:
            reply = self.inner.complete(system, user, images=images)
        else:
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

    def __init__(
        self,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        vision_model: str | None = None,
        vision_base_url: str | None = None,
        vision_api_key: str | None = None,
    ) -> None:
        """Requests with photos go to the vision model, which defaults to the text model.

        Many text models cannot see images, so the vision model may be a different one and
        may even live at another provider.
        """
        from openai import OpenAI

        self.model = model
        self.vision_model = vision_model or model
        # Local servers ignore the key, but the SDK refuses to start without one.
        self.client = OpenAI(base_url=base_url, api_key=api_key or "not-needed")
        self.vision_client = (
            OpenAI(
                base_url=vision_base_url or base_url,
                api_key=vision_api_key or api_key or "not-needed",
            )
            if vision_base_url or vision_api_key
            else self.client
        )

    def complete(self, system: str, user: str, images: Sequence[Image] = ()) -> Reply:
        from openai import OpenAIError

        content: str | list[dict] = user
        if images:
            content = [{"type": "text", "text": user}]
            for image in images:
                encoded = base64.b64encode(image.data).decode("ascii")
                url = f"data:{image.media_type};base64,{encoded}"
                content.append({"type": "image_url", "image_url": {"url": url}})
        client = self.vision_client if images else self.client
        name = self.vision_model if images else self.model
        try:
            response = client.chat.completions.create(
                model=name,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": content},
                ],
            )
        except OpenAIError as error:
            hint = (
                f" Photos need a model that can see images; '{name}' may not. "
                "Set RAGWIKI_VISION_MODEL to one that can."
                if images
                else ""
            )
            raise ModelError(f"The model request failed: {error}.{hint}") from error
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
    value = _env_float("RAGWIKI_CONTEXT_TOKENS")
    if value is None:
        return DEFAULT_CONTEXT_TOKENS
    if value < 1:
        raise ConfigError(f"RAGWIKI_CONTEXT_TOKENS must be a positive number, got '{value:g}'")
    return int(value)


def model_from_env() -> OpenAICompatibleModel:
    name = os.environ.get("RAGWIKI_MODEL")
    if not name:
        raise ConfigError(
            "No model configured. Set RAGWIKI_MODEL (and RAGWIKI_BASE_URL and "
            "RAGWIKI_API_KEY for your provider). See the README for examples."
        )
    return OpenAICompatibleModel(
        model=name,
        base_url=os.environ.get("RAGWIKI_BASE_URL") or None,
        api_key=os.environ.get("RAGWIKI_API_KEY") or None,
        vision_model=os.environ.get("RAGWIKI_VISION_MODEL") or None,
        vision_base_url=os.environ.get("RAGWIKI_VISION_BASE_URL") or None,
        vision_api_key=os.environ.get("RAGWIKI_VISION_API_KEY") or None,
    )


def prices_from_env() -> tuple[float, float]:
    """Input and output price in USD per million tokens; zero when not configured."""
    return (
        _env_float("RAGWIKI_PRICE_INPUT") or 0.0,
        _env_float("RAGWIKI_PRICE_OUTPUT") or 0.0,
    )


def metered_from_env(log_path: Path) -> MeteredModel:
    price_input, price_output = prices_from_env()
    return MeteredModel(
        model_from_env(),
        log_path,
        price_input=price_input,
        price_output=price_output,
        max_usd=_env_float("RAGWIKI_MAX_USD"),
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
