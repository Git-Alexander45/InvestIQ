"""Builds provider instances from configuration. Missing keys -> provider unavailable (not an error)."""

from __future__ import annotations

from datetime import date

import logging
from dataclasses import dataclass, field

from investiq.config import Settings
from investiq.data.providers.bank_of_canada import BankOfCanadaFx
from investiq.data.providers.base import ProviderNotConfigured
from investiq.data.providers.fmp import FmpProvider
from investiq.data.providers.rss import RssProvider
from investiq.data.providers.sec_edgar import SecEdgarFundamentals
from investiq.data.providers.synthetic import SyntheticProvider
from investiq.data.providers.twelvedata import TwelveDataProvider
from investiq.services.preferences import MarketData

log = logging.getLogger(__name__)


class SyntheticRefused(RuntimeError):
    pass


@dataclass
class Providers:
    prices: object | None = None
    fundamentals: object | None = None
    sec: object | None = None
    holdings: object | None = None
    actions: object | None = None
    fx: object | None = None
    rss: object | None = None
    company_news: object | None = None
    unavailable: dict[str, str] = field(default_factory=dict)
    synthetic: bool = False


def build(settings: Settings, prefs: MarketData, today: date | None = None) -> Providers:
    p = Providers(rss=RssProvider())
    wants_synth = "synthetic" in (prefs.price_provider, prefs.fundamentals_provider, prefs.etf_holdings_provider,
                                  prefs.fx_provider)
    if wants_synth:
        if settings.is_production or not settings.allow_synthetic_data:
            raise SyntheticRefused("Synthetic data is disabled. It is allowed only in development with "
                                   "INVESTIQ_ALLOW_SYNTHETIC_DATA=true and never in production.")
        p.synthetic = True
    synth = SyntheticProvider(today=today) if wants_synth else None

    fmp = twelve = sec = None
    try:
        fmp = FmpProvider(settings.secret("fmp_api_key"))
    except ProviderNotConfigured as exc:
        p.unavailable["fmp"] = str(exc)
    try:
        twelve = TwelveDataProvider(settings.secret("twelvedata_api_key"))
    except ProviderNotConfigured as exc:
        p.unavailable["twelvedata"] = str(exc)
    try:
        sec = SecEdgarFundamentals(settings.sec_user_agent)
    except ProviderNotConfigured as exc:
        p.unavailable["sec_edgar"] = str(exc)

    p.prices = {"fmp": fmp, "twelvedata": twelve, "synthetic": synth, "none": None}[prefs.price_provider]
    p.fundamentals = {"fmp": fmp, "sec_edgar": sec, "synthetic": synth, "none": None}[prefs.fundamentals_provider]
    p.sec = sec
    p.holdings = {"fmp": fmp, "synthetic": synth, "none": None}[prefs.etf_holdings_provider]
    p.actions = fmp if prefs.price_provider == "fmp" else (synth if prefs.price_provider == "synthetic" else fmp)
    p.fx = synth if prefs.fx_provider == "synthetic" else BankOfCanadaFx()
    p.company_news = fmp
    if p.prices is None and prefs.price_provider != "none":
        p.unavailable.setdefault("prices", f"price provider '{prefs.price_provider}' is not configured")
    return p
