"""Rules-based news interpretation (the always-available, zero-cost baseline).

Produces the same structured fields as the AI news researcher, with deliberately modest
confidence. When the AI budget is available the top items are re-assessed by a low-cost model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TOPICS: dict[str, list[str]] = {
    "central_bank": ["interest rate", "rate decision", "policy rate", "monetary policy", "fomc", "bank of canada",
                     "federal reserve", "ecb", "rate cut", "rate hike", "basis points", "quantitative"],
    "inflation": ["inflation", "cpi", "consumer price", "pce", "price index"],
    "employment": ["jobs", "employment", "unemployment", "payrolls", "labour force", "labor force", "jobless"],
    "tariffs_trade": ["tariff", "trade agreement", "trade deal", "duties", "export controls", "import", "usmca", "cusma"],
    "elections_politics": ["election", "parliament", "congress", "senate", "prime minister", "president", "budget",
                           "legislation", "government shutdown"],
    "geopolitics": ["war", "conflict", "sanction", "invasion", "military", "ceasefire", "missile", "geopolitical"],
    "regulation": ["regulator", "regulation", "antitrust", "sec charges", "lawsuit", "probe", "investigation",
                   "fine", "settlement", "approval", "fda"],
    "earnings": ["earnings", "quarterly results", "revenue", "guidance", "profit", "eps", "outlook"],
    "insider": ["insider", "director buys", "ceo sells", "form 4"],
    "institutional": ["13f", "stake", "activist", "institutional"],
    "technology": ["ai ", "artificial intelligence", "chip", "semiconductor", "quantum", "launch", "patent"],
    "supply_chain": ["supply chain", "shortage", "logistics", "shipping", "port", "inventory"],
    "energy": ["oil", "crude", "natural gas", "opec", "pipeline", "lng", "uranium", "nuclear"],
    "commodities": ["gold", "silver", "copper", "wheat", "commodity", "lithium", "metals"],
    "economic_reports": ["gdp", "retail sales", "housing starts", "pmi", "trade balance", "industrial production"],
    "corporate_action": ["acquire", "acquisition", "merger", "buyback", "dividend", "spin-off", "split", "ipo"],
}
SECTOR_KEYWORDS: dict[str, list[str]] = {
    "Technology": ["software", "chip", "semiconductor", "cloud", "ai ", "artificial intelligence", "cyber"],
    "Financials": ["bank", "lender", "insurer", "mortgage", "credit"],
    "Energy": ["oil", "gas", "pipeline", "opec", "crude", "lng"],
    "Health Care": ["drug", "fda", "biotech", "pharma", "hospital", "vaccine"],
    "Industrials": ["rail", "aerospace", "defence", "defense", "manufactur", "machinery"],
    "Materials": ["mining", "miner", "gold", "copper", "lithium", "steel", "fertilizer", "potash"],
    "Utilities": ["utility", "electricity", "power grid"],
    "Consumer Discretionary": ["retail", "automaker", "e-commerce", "consumer spending"],
    "Consumer Staples": ["grocery", "food", "beverage", "household products"],
    "Communication Services": ["telecom", "wireless", "streaming", "media", "advertising"],
    "Real Estate": ["reit", "real estate", "property"],
}
POSITIVE = ["beats", "beat estimates", "raises guidance", "raised guidance", "record", "upgrade", "approval", "approved",
            "surge", "growth accelerat", "wins contract", "expands", "rate cut", "cuts rates", "ceasefire",
            "trade deal", "exceeds", "strong demand", "buyback", "dividend increase", "raises dividend"]
NEGATIVE = ["misses", "missed estimates", "cuts guidance", "lowers guidance", "downgrade", "recall", "lawsuit",
            "probe", "investigation", "plunge", "layoffs", "bankruptcy", "default", "sanction", "tariff hike",
            "new tariffs", "rate hike", "raises rates", "war", "invasion", "shortage", "fraud", "halt", "warning",
            "dividend cut", "slump", "recession"]
RUMOUR = ["reportedly", "sources say", "people familiar", "rumor", "rumour", "could", "considering", "in talks"]
LONG_TERM_TOPICS = {"regulation", "tariffs_trade", "geopolitics", "technology", "elections_politics",
                    "corporate_action"}
TOPIC_IMPORTANCE = {"central_bank": 0.9, "inflation": 0.8, "employment": 0.7, "tariffs_trade": 0.8,
                    "geopolitics": 0.8, "earnings": 0.7, "regulation": 0.6, "economic_reports": 0.6,
                    "energy": 0.6, "commodities": 0.5, "elections_politics": 0.6, "corporate_action": 0.6}


@dataclass
class EntityIndex:
    """Instrument symbols and names that can be matched in text."""

    by_symbol: dict[str, str] = field(default_factory=dict)  # SYMBOL -> canonical symbol
    by_name: dict[str, str] = field(default_factory=dict)  # lowercase distinctive name -> symbol

    @classmethod
    def build(cls, rows: list[tuple[str, str]]) -> EntityIndex:
        idx = cls()
        for symbol, name in rows:
            sym = symbol.upper()
            idx.by_symbol[sym] = sym
            core = re.sub(r"\b(inc|corp|corporation|ltd|limited|plc|co|company|group|holdings|the|etf|index|fund|"
                          r"trust|class [a-z])\b\.?", "", name.lower())
            core = " ".join(core.replace(",", " ").split())
            if len(core) >= 5:
                idx.by_name[core] = sym
        return idx

    def match(self, text: str) -> list[str]:
        found: set[str] = set()
        for m in re.finditer(r"\$([A-Z]{1,6}(?:\.[A-Z])?)\b|\(([A-Z]{1,6}(?:\.[A-Z])?)\)|(?:NYSE|NASDAQ|TSX):\s?([A-Z.]{1,7})",
                             text):
            sym = next(g for g in m.groups() if g)
            if sym in self.by_symbol:
                found.add(sym)
        low = text.lower()
        for name, sym in self.by_name.items():
            if re.search(rf"\b{re.escape(name)}\b", low):
                found.add(sym)
        return sorted(found)


@dataclass
class RuleAssessment:
    topic: str
    what_happened: str
    confirmation: str
    impact: str
    horizon: str
    confidence: float
    importance: float
    affected_symbols: list[str]
    affected_sectors: list[str]
    evidence: list[str]


def _hits(text: str, words: list[str]) -> list[str]:
    return [w for w in words if w in text]


def assess(title: str, summary: str | None, *, official: bool, entities: EntityIndex) -> RuleAssessment:
    text = f" {title} {summary or ''} ".lower()
    topic_hits = {t: len(_hits(text, kws)) for t, kws in TOPICS.items()}
    topic = max(topic_hits, key=lambda t: topic_hits[t]) if any(topic_hits.values()) else "general"
    pos, neg = _hits(text, POSITIVE), _hits(text, NEGATIVE)
    if pos and neg:
        impact = "mixed"
    elif pos:
        impact = "positive"
    elif neg:
        impact = "negative"
    else:
        impact = "uncertain"
    rumour = _hits(text, RUMOUR)
    confirmation = "confirmed" if official else ("rumour" if rumour else "reported")
    symbols = entities.match(f"{title} {summary or ''}")
    sectors = sorted(s for s, kws in SECTOR_KEYWORDS.items() if _hits(text, kws))
    confidence = 0.25 + (0.15 if official else 0) + (0.1 if (pos or neg) and not (pos and neg) else 0)
    importance = TOPIC_IMPORTANCE.get(topic, 0.4) * (1.2 if official else 1.0) + 0.1 * min(len(symbols), 3)
    evidence = [f"keyword:{w}" for w in (pos + neg)[:5]] + [f"topic:{topic}"]
    return RuleAssessment(topic=topic, what_happened=title.strip(), confirmation=confirmation, impact=impact,
                          horizon="long_term" if topic in LONG_TERM_TOPICS else "short_term",
                          confidence=round(min(confidence, 0.5), 2), importance=round(min(importance, 1.0), 2),
                          affected_symbols=symbols, affected_sectors=sectors, evidence=evidence)
