"""ETF overlap, look-through exposure and concentration measures."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field


@dataclass
class Constituent:
    key: str  # normalised identifier (symbol or name)
    name: str
    weight_pct: float
    sector: str | None = None
    country: str | None = None
    currency: str | None = None
    asset_class: str | None = None


def normalise_key(symbol: str | None, name: str) -> str:
    if symbol:
        return symbol.upper().split(".")[0].replace("-", ".")
    return " ".join(name.upper().replace(",", " ").replace(".", " ").split())


def pairwise_overlap(a: Iterable[Constituent], b: Iterable[Constituent]) -> float:
    """Weight overlap in percent: sum over common holdings of min(weight_a, weight_b)."""
    wa: dict[str, float] = defaultdict(float)
    wb: dict[str, float] = defaultdict(float)
    for c in a:
        wa[c.key] += c.weight_pct
    for c in b:
        wb[c.key] += c.weight_pct
    return sum(min(wa[k], wb[k]) for k in wa.keys() & wb.keys())


def overlap_matrix(funds: Mapping[str, list[Constituent]]) -> dict[str, dict[str, float]]:
    names = list(funds)
    out: dict[str, dict[str, float]] = {n: {} for n in names}
    for i, x in enumerate(names):
        for y in names[i:]:
            v = 100.0 if x == y else pairwise_overlap(funds[x], funds[y])
            out[x][y] = out[y][x] = round(v, 4)
    return out


@dataclass
class Exposure:
    by_company: dict[str, float] = field(default_factory=dict)
    by_sector: dict[str, float] = field(default_factory=dict)
    by_country: dict[str, float] = field(default_factory=dict)
    by_currency: dict[str, float] = field(default_factory=dict)
    by_asset_class: dict[str, float] = field(default_factory=dict)
    company_names: dict[str, str] = field(default_factory=dict)
    unexplained_pct: float = 0.0  # portfolio weight with no look-through data


def look_through(positions: list[tuple[float, list[Constituent] | None, Constituent]]) -> Exposure:
    """Combine positions into look-through exposures.

    Each position is ``(portfolio_weight_pct, constituents_or_None, self_as_constituent)``.
    ETFs with holdings are expanded; positions without holdings count as themselves.
    Missing constituent attributes are bucketed as "Unknown" rather than guessed.
    """
    exp = Exposure()
    acc: dict[str, dict[str, float]] = {k: defaultdict(float) for k in
                                         ("company", "sector", "country", "currency", "asset_class")}
    for weight, constituents, itself in positions:
        if constituents:
            captured = sum(c.weight_pct for c in constituents)
            scale = weight / 100.0
            for c in constituents:
                w = c.weight_pct * scale
                acc["company"][c.key] += w
                exp.company_names.setdefault(c.key, c.name)
                acc["sector"][c.sector or "Unknown"] += w
                acc["country"][c.country or "Unknown"] += w
                acc["currency"][c.currency or "Unknown"] += w
                acc["asset_class"][c.asset_class or itself.asset_class or "Unknown"] += w
            residual = weight * max(0.0, 100.0 - captured) / 100.0
            if residual > 1e-9:
                exp.unexplained_pct += residual
                for dim in ("sector", "country", "currency"):
                    acc[dim]["Unknown"] += residual
                acc["asset_class"][itself.asset_class or "Unknown"] += residual
        else:
            if itself.asset_class == "etf":
                exp.unexplained_pct += weight
            acc["company"][itself.key] += weight
            exp.company_names.setdefault(itself.key, itself.name)
            acc["sector"][itself.sector or "Unknown"] += weight
            acc["country"][itself.country or "Unknown"] += weight
            acc["currency"][itself.currency or "Unknown"] += weight
            acc["asset_class"][itself.asset_class or "Unknown"] += weight
    exp.by_company = _sorted(acc["company"])
    exp.by_sector = _sorted(acc["sector"])
    exp.by_country = _sorted(acc["country"])
    exp.by_currency = _sorted(acc["currency"])
    exp.by_asset_class = _sorted(acc["asset_class"])
    return exp


def _sorted(d: Mapping[str, float]) -> dict[str, float]:
    return {k: round(v, 4) for k, v in sorted(d.items(), key=lambda kv: -kv[1]) if abs(v) > 1e-9}


def herfindahl(weights_pct: Iterable[float]) -> float:
    """HHI on a 0..1 scale using fractional weights."""
    ws = [w / 100.0 for w in weights_pct if w > 0]
    total = sum(ws)
    if total <= 0:
        return 0.0
    return sum((w / total) ** 2 for w in ws)


def effective_number(weights_pct: Iterable[float]) -> float:
    h = herfindahl(weights_pct)
    return 1.0 / h if h > 0 else 0.0


def top_n_concentration(weights_pct: Iterable[float], n: int = 10) -> float:
    return sum(sorted((w for w in weights_pct if w > 0), reverse=True)[:n])
