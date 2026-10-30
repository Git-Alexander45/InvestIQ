import json
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from investiq.ai import budget
from investiq.ai.evidence import EvidencePack, check_citations
from investiq.ai.pricing import UnknownModelPrice, load_prices
from investiq.ai.providers import AiProviderError, Completion, UsagePart, strict_schema
from investiq.ai.router import ModelRouter
from investiq.ai.schemas import ChiefAnalystOut, NewsBatchOut
from investiq.models import AiRequest, FxRate
from investiq.services.preferences import set_pref


class FakeProvider:
    name = "anthropic"

    def __init__(self, payload=None, *, stop="end_turn", usage=None, error=None, served="claude-opus-5-5"):
        self.payload, self.stop, self.error, self.served = payload, stop, error, served
        self.usage = usage or [UsagePart(served, 2000, 1000)]
        self.calls = []

    def complete(self, **kw):
        self.calls.append(kw)
        if self.error:
            raise self.error
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return Completion(text=text, stop_reason=self.stop, served_model=self.served, usage=self.usage,
                          request_id="req_test", latency_ms=5)


def router_for(session, provider, engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    return ModelRouter(session, provider_factory=lambda name: provider, ledger_session_factory=factory)


def chief_payload(evidence=("N1",)):
    claim = {"text": "Rates held", "evidence": list(evidence)}
    return {"market_overview": "Calm", "key_developments": [claim], "political_developments": [],
            "economic_developments": [], "top_conclusions": [claim], "important_risks": [],
            "wait_rationale": "Valuations are stretched; waiting is reasonable."}


def pack():
    p = EvidencePack(subject="t")
    p.add("news", "Bank of Canada holds rate", "boc", "2026-10-29")
    return p


def test_pricing_table_and_unknown_model():
    prices = load_prices()
    opus = prices.get("claude-opus-5-5")
    assert opus.cost_usd(1_000_000, 0) == pytest.approx(4.0)
    assert opus.cost_usd(0, 1_000_000) == pytest.approx(20.0)
    haiku = prices.get("claude-haiku-5-5")
    assert haiku.cost_usd(200_000, 0) == pytest.approx(0.10)  # long-context rate above 100K
    with pytest.raises(UnknownModelPrice):
        prices.get("gpt-unknown")


def test_strict_schema_closes_objects():
    s = strict_schema(NewsBatchOut.model_json_schema())
    item = s["$defs"]["NewsItemAssessment"]
    assert item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])
    assert "maximum" not in json.dumps(s)


def test_citation_check():
    p = pack()
    out = ChiefAnalystOut.model_validate(chief_payload(["N1"]))
    assert check_citations(out, p).acceptable
    bad = ChiefAnalystOut.model_validate(chief_payload(["N9"]))
    chk = check_citations(bad, p)
    assert chk.invalid_ids == ["N9"] and not chk.acceptable
    none = ChiefAnalystOut.model_validate(chief_payload([]))
    assert check_citations(none, p).unsupported_ratio == 1.0


def test_router_success_records_cost_in_cad(session, engine):
    session.add(FxRate(base="USD", quote="CAD", rate=1.40, as_of=datetime.now(UTC).date(), source="Bank of Canada"))
    session.commit()
    prov = FakeProvider(chief_payload())
    r = router_for(session, prov, engine).run(task="chief", role="chief_analyst", tier="premium", pack=pack(),
                                              schema=ChiefAnalystOut)
    assert r.status == "ok" and r.output.wait_rationale
    req = session.execute(select(AiRequest)).scalar_one()
    expected_usd = (2000 * 4 + 1000 * 20) / 1e6
    assert req.cost_usd == pytest.approx(expected_usd)
    assert req.cost_cad == pytest.approx(expected_usd * 1.40)
    assert req.model == "claude-opus-5-5" and req.input_tokens == 2000 and req.output_tokens == 1000
    assert "Bank of Canada" in req.usd_cad_source
    call = prov.calls[0]
    assert call["effort"] == "medium" and call["schema"]["additionalProperties"] is False
    assert "Investment Constitution" in call["system"]


def test_budget_hard_limit_blocks_and_records(session, engine):
    set_pref(session, "ai_budget", {"monthly_limit_cad": 0.01})
    session.commit()
    prov = FakeProvider(chief_payload())
    r = router_for(session, prov, engine).run(task="chief", role="chief_analyst", tier="premium", pack=pack(),
                                              schema=ChiefAnalystOut)
    assert r.status == "blocked_budget"
    assert prov.calls == []  # never reached the provider
    req = session.execute(select(AiRequest)).scalar_one()
    assert req.status == "blocked_budget" and req.cost_cad == 0


def test_budget_paused_when_spent(session, engine):
    set_pref(session, "ai_budget", {"monthly_limit_cad": 1.0})
    session.add(AiRequest(task="x", role="x", tier="premium", provider="anthropic", model="claude-opus-5-5",
                          prompt_version="v", status="ok", cost_cad=1.0, usd_cad_rate=1.4, usd_cad_source="t",
                          pricing_version="p", budget_month=budget.budget_month()))
    session.commit()
    st = budget.status(session)
    assert st.paused and st.remaining_cad <= 0
    r = router_for(session, FakeProvider(chief_payload()), engine)
    ok, why = r.available("low_cost")
    assert not ok and "paused" in why


def test_premium_reserve_stops_premium_first(session, engine):
    set_pref(session, "ai_budget", {"monthly_limit_cad": 5.0, "premium_reserve_pct": 50})
    session.add(AiRequest(task="x", role="x", tier="premium", provider="anthropic", model="m", prompt_version="v",
                          status="ok", cost_cad=3.0, usd_cad_rate=1.4, usd_cad_source="t", pricing_version="p",
                          budget_month=budget.budget_month()))
    session.commit()
    r = router_for(session, FakeProvider(chief_payload()), engine)
    assert r.available("premium")[0] is False
    assert r.available("low_cost")[0] is True


def test_budget_never_raised_automatically(session):
    with pytest.raises(PermissionError):
        set_pref(session, "ai_budget", {"monthly_limit_cad": 50}, actor="system")
    set_pref(session, "ai_budget", {"monthly_limit_cad": 3}, actor="system")  # lowering is allowed


def test_invalid_output_and_refusal_and_error(session, engine):
    r = router_for(session, FakeProvider("not json"), engine).run(
        task="c", role="chief_analyst", tier="premium", pack=pack(), schema=ChiefAnalystOut)
    assert r.status == "invalid_output" and r.output is None
    r2 = router_for(session, FakeProvider(chief_payload(["Z1"])), engine).run(
        task="c", role="chief_analyst", tier="premium", pack=pack(), schema=ChiefAnalystOut)
    assert r2.status == "invalid_output" and "citation" in r2.error
    r3 = router_for(session, FakeProvider(None, stop="refusal"), engine).run(
        task="c", role="chief_analyst", tier="premium", pack=pack(), schema=ChiefAnalystOut)
    assert r3.status == "refusal"
    r4 = router_for(session, FakeProvider(error=AiProviderError("boom")), engine).run(
        task="c", role="chief_analyst", tier="premium", pack=pack(), schema=ChiefAnalystOut)
    assert r4.status == "error"
    statuses = sorted(r.status for r in session.execute(select(AiRequest)).scalars())
    assert statuses == ["error", "invalid_output", "invalid_output", "refusal"]


def test_fallback_usage_priced_per_served_model(session, engine):
    usage = [UsagePart("claude-opus-5-5", 1000, 100), UsagePart("claude-opus-4-8", 1000, 500)]
    prov = FakeProvider(chief_payload(), usage=usage, served="claude-opus-4-8")
    router_for(session, prov, engine).run(task="c", role="chief_analyst", tier="premium", pack=pack(),
                                          schema=ChiefAnalystOut)
    req = session.execute(select(AiRequest)).scalar_one()
    assert req.cost_usd == pytest.approx((1000 * 4 + 100 * 20 + 1000 * 5 + 500 * 25) / 1e6)
    assert req.served_model == "claude-opus-4-8"


def test_unavailable_without_key(session):
    r = ModelRouter(session)
    ok, why = r.available("premium")
    assert not ok and "ANTHROPIC_API_KEY" in why


def test_daily_usage(session, engine):
    router_for(session, FakeProvider(chief_payload()), engine).run(
        task="chief", role="chief_analyst", tier="premium", pack=pack(), schema=ChiefAnalystOut)
    days = budget.daily_usage(session)
    assert days and days[0]["cost_cad"] > 0 and "chief" in days[0]["by_task"]
    assert date.fromisoformat(days[0]["date"])
