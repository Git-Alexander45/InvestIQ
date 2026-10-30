"""Model price table and cost estimation."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from investiq.config import REPO_ROOT

PRICING_FILE = REPO_ROOT / "config" / "model_pricing.yaml"


class UnknownModelPrice(LookupError):
    pass


@dataclass(frozen=True)
class ModelPrice:
    model: str
    input: float
    output: float
    long_context_threshold: int | None = None
    long_input: float | None = None
    long_output: float | None = None

    def cost_usd(self, input_tokens: int, output_tokens: int) -> float:
        inp, out = self.input, self.output
        if self.long_context_threshold and input_tokens > self.long_context_threshold:
            inp, out = self.long_input or inp, self.long_output or out
        return (input_tokens * inp + output_tokens * out) / 1_000_000


@dataclass(frozen=True)
class PriceTable:
    version: str
    verified_on: str
    prices: dict[str, ModelPrice]

    def get(self, model: str) -> ModelPrice:
        try:
            return self.prices[model]
        except KeyError as exc:
            raise UnknownModelPrice(f"No verified price for model '{model}'; add it to {PRICING_FILE.name}") from exc

    def most_expensive(self) -> ModelPrice:
        return max(self.prices.values(), key=lambda p: (p.output, p.input))


@lru_cache
def load_prices(path: Path = PRICING_FILE) -> PriceTable:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    prices = {
        name: ModelPrice(model=name, input=float(v["input"]), output=float(v["output"]),
                         long_context_threshold=v.get("long_context_threshold"),
                         long_input=v.get("long_input"), long_output=v.get("long_output"))
        for name, v in data["models"].items()
    }
    return PriceTable(version=str(data["version"]), verified_on=str(data["verified_on"]), prices=prices)


def estimate_input_tokens(text: str) -> int:
    """Conservative upper estimate (about 3 characters per token) used for budget reservation."""
    return max(1, len(text) // 3 + 50)
