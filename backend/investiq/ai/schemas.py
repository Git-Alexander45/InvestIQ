"""Validated output contracts for every AI role. Claims must cite evidence IDs from the pack."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Assessment = Literal["BUY", "WATCH", "HOLD", "SELL", "AVOID"]
Impact = Literal["positive", "negative", "mixed", "uncertain"]


class Claim(BaseModel):
    text: str
    evidence: list[str] = Field(description="IDs from the evidence pack, e.g. F3, N2. Empty if none.")


class ScoredView(BaseModel):
    score: float = Field(ge=0, le=100)
    rationale: str
    evidence: list[str]


class Estimate(BaseModel):
    statement: str
    basis: str = Field(description="How the estimate was formed; estimates are never facts.")


class NewsItemAssessment(BaseModel):
    news_id: str
    topic: str
    what_happened: str
    event_time: str | None
    confirmation: Literal["confirmed", "reported", "rumour", "unknown"]
    impact: Impact
    horizon: Literal["short_term", "long_term", "unclear"]
    confidence: float = Field(ge=0, le=1)
    importance: float = Field(ge=0, le=1)
    affected_symbols: list[str]
    affected_sectors: list[str]
    reasoning: str
    evidence: list[str]


class NewsBatchOut(BaseModel):
    items: list[NewsItemAssessment]


class InvestmentAnalysisOut(BaseModel):
    thesis: str
    bull_case: list[Claim]
    bear_case: list[Claim]
    growth: ScoredView
    competitive_advantage: ScoredView
    industry_trends: ScoredView
    valuation_stance: Literal["attractive", "fair", "stretched", "unknown"]
    valuation_rationale: Claim
    key_risks: list[Claim]
    catalysts: list[Claim]
    portfolio_fit_comment: str
    recommendation: Assessment
    reasons_to_avoid: list[str]
    confidence: float = Field(ge=0, le=1)
    horizon: str
    estimates: list[Estimate]
    unknowns: list[str]


class ReviewOut(BaseModel):
    agrees: bool
    recommended_assessment: Assessment
    unsupported_assumptions: list[str]
    overlooked_risks: list[Claim]
    alternative_interpretations: list[str]
    summary: str


class RiskReviewOut(BaseModel):
    portfolio_risks: list[Claim]
    concentration_comments: list[Claim]
    candidates_to_downgrade: list[str] = Field(description="Symbols whose addition would weaken the portfolio")
    summary: str


class ChiefAnalystOut(BaseModel):
    market_overview: str
    key_developments: list[Claim]
    political_developments: list[Claim]
    economic_developments: list[Claim]
    top_conclusions: list[Claim]
    important_risks: list[Claim]
    wait_rationale: str = Field(description="Why waiting/holding cash is or is not appropriate today")
