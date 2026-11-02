import pytest

from investiq.diversification.engine import Position, analyse, what_if
from investiq.finance import overlap as ov
from investiq.services.preferences import RiskLimits

LIMITS = RiskLimits().model_dump()


def c(sym, w, sector="Technology", country="US"):
    return ov.Constituent(ov.normalise_key(sym, sym), sym, w, sector, country, None, "equity")


def test_pairwise_overlap():
    a = [c("AAPL", 7), c("MSFT", 6), c("NVDA", 5), c("XOM", 2)]
    b = [c("AAPL", 12), c("MSFT", 10), c("JPM", 3)]
    assert ov.pairwise_overlap(a, b) == pytest.approx(7 + 6)
    m = ov.overlap_matrix({"A": a, "B": b})
    assert m["A"]["B"] == m["B"]["A"] == pytest.approx(13)
    assert m["A"]["A"] == 100.0


def test_effective_number_and_hhi():
    assert ov.effective_number([25, 25, 25, 25]) == pytest.approx(4)
    assert ov.herfindahl([100]) == 1.0
    assert ov.top_n_concentration([5, 10, 1, 20], 2) == 30


def test_normalise_key():
    assert ov.normalise_key("brk-b", "Berkshire") == "BRK.B"
    assert ov.normalise_key(None, "Apple, Inc.") == "APPLE INC"


def _etf(sym, constituents, value):
    return Position(1 if sym == "QQQ" else 2, sym, "NASDAQ", sym, "equity", "etf", value, "USD", "US",
                    constituents=constituents)


def test_lookthrough_reveals_hidden_concentration():
    qqq = [c("AAPL", 9), c("MSFT", 8.5), c("NVDA", 8), c("AMZN", 7)]
    spy = [c("AAPL", 7), c("MSFT", 6.5), c("NVDA", 6), c("JPM", 2, "Financials")]
    rep = analyse([_etf("QQQ", qqq, 50_000), _etf("VOO", spy, 50_000)], cash_cad=0, limits=LIMITS)
    assert rep.top_companies[0]["key"] == "AAPL"
    assert rep.top_companies[0]["weight_pct"] == pytest.approx(8.0)
    assert rep.etf_overlap["QQQ"]["VOO"] == pytest.approx(7 + 6.5 + 6)
    assert rep.by_sector["Technology"] > 25
    assert any(f["type"] == "sector_concentration" for f in rep.flags)
    # residual (unknown) weight is reported, not guessed
    assert rep.lookthrough_coverage_pct < 50
    assert any(f["type"] == "data_coverage" for f in rep.flags)


def test_position_size_flag_and_cash():
    stock = Position(3, "NVDA", "NASDAQ", "NVIDIA", "equity", "common_stock", 20_000, "USD", "US", "Technology")
    rep = analyse([stock], cash_cad=80_000, limits=LIMITS)
    assert rep.weights["NVDA"] == pytest.approx(20)
    assert rep.by_asset_class["cash"] == pytest.approx(80)
    assert any(f["type"] == "position_size" for f in rep.flags)
    assert rep.by_underlying_currency["USD"] == pytest.approx(20)


def test_hedged_fund_counts_as_cad_exposure():
    p = Position(4, "XSP", "TSX", "XSP", "equity", "etf", 10_000, "CAD", "CA", currency_hedged=True,
                 constituents=[c("AAPL", 100)])
    rep = analyse([p], 0, LIMITS)
    assert rep.by_underlying_currency.get("CAD") == pytest.approx(100)


def test_what_if_rejects_concentrating_addition():
    tech = Position(5, "XIT", "TSX", "Tech ETF", "equity", "etf", 28_000, "CAD", "CA",
                    constituents=[c("SHOP", 50, "Technology", "CA"), c("CSU", 50, "Technology", "CA")])
    bank = Position(6, "ZEB", "TSX", "Banks", "equity", "etf", 72_000, "CAD", "CA",
                    constituents=[c(f"B{i}", 100 / 6, "Financials", "CA") for i in range(6)])
    cand = Position(7, "NVDA", "NASDAQ", "NVIDIA", "equity", "common_stock", 0, "USD", "US", "Technology")
    fit, before, after = what_if([tech, bank], 0, cand, 7.0, LIMITS)
    assert not fit.acceptable
    assert any("Technology" in f for f in fit.flags)
    assert after.by_sector["Technology"] > before.by_sector["Technology"]
    # A defensive addition is fine
    util = Position(8, "FTS", "TSX", "Fortis", "equity", "common_stock", 0, "CAD", "CA", "Utilities")
    fit2, _, _ = what_if([tech, bank], 10_000, util, 5.0, LIMITS)
    assert fit2.acceptable
