"""AI provider adapters behind one small interface, so providers stay interchangeable.

Only an Anthropic adapter ships today; adding another provider means implementing
``AiProvider.complete`` and adding its models to ``config/model_pricing.yaml``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

import anthropic

# Server-side refusal fallback (Claude API): on a policy refusal the API re-runs the request on
# an Anthropic-recommended fallback model inside the same call.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-1"}


@dataclass
class UsagePart:
    model: str
    input_tokens: int
    output_tokens: int


@dataclass
class Completion:
    text: str | None
    stop_reason: str | None
    served_model: str
    usage: list[UsagePart]
    request_id: str | None
    latency_ms: int
    raw_meta: dict[str, Any] = field(default_factory=dict)


class AiProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class AiProvider(Protocol):
    name: str

    def complete(self, *, model: str, system: str, user: str, schema: dict[str, Any], max_tokens: int,
                 effort: str) -> Completion: ...


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str | None, client: anthropic.Anthropic | None = None, timeout_s: float = 300.0) -> None:
        if client is None and not api_key:
            raise AiProviderError("ANTHROPIC_API_KEY is not configured")
        self._client = client or anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)

    def complete(self, *, model: str, system: str, user: str, schema: dict[str, Any], max_tokens: int,
                 effort: str) -> Completion:
        params: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "output_config": {"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        }
        started = time.monotonic()
        try:
            if model in FALLBACK_MODELS:
                resp = self._client.beta.messages.create(**params, betas=[FALLBACK_BETA], fallbacks="default")
            else:
                resp = self._client.messages.create(**params)
        except anthropic.RateLimitError as exc:
            raise AiProviderError(f"rate limited: {exc.message}", retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise AiProviderError(f"API error {exc.status_code}: {exc.message}", retryable=exc.status_code >= 500) from exc
        except anthropic.APIConnectionError as exc:
            raise AiProviderError(f"connection error: {exc}", retryable=True) from exc
        latency = int((time.monotonic() - started) * 1000)

        text = None
        if resp.stop_reason != "refusal":
            text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
        return Completion(text=text, stop_reason=resp.stop_reason, served_model=resp.model,
                          usage=_usage_parts(resp), request_id=getattr(resp, "_request_id", None),
                          latency_ms=latency)


def _usage_parts(resp: Any) -> list[UsagePart]:
    """Per-model token usage. With server-side fallback, iterations may span several models."""
    usage = resp.usage
    iterations = getattr(usage, "iterations", None) or []
    parts = []
    for it in iterations:
        model = getattr(it, "model", None)
        if model:
            parts.append(UsagePart(model, int(getattr(it, "input_tokens", 0) or 0),
                                   int(getattr(it, "output_tokens", 0) or 0)))
    if parts:
        return parts
    return [UsagePart(resp.model, int(usage.input_tokens or 0), int(usage.output_tokens or 0))]


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic JSON schema suitable for structured outputs: closed objects, every property
    required (optional values are nullable), and validation keywords removed (Pydantic re-validates)."""
    drop = {"title", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "minLength",
            "maxLength", "minItems", "maxItems", "pattern", "format", "examples"}

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            out = {k: walk(v) for k, v in node.items() if k not in drop}
            if out.get("type") == "object" or "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out.get("properties", {}).keys())
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(json.loads(json.dumps(schema)))
