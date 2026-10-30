"""Provider-independent model router with budget enforcement, structured output validation and
full request accounting. Every call (including blocked and failed ones) is recorded."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from investiq.ai import budget
from investiq.ai.evidence import CitationCheck, EvidencePack, check_citations
from investiq.ai.pricing import UnknownModelPrice, estimate_input_tokens, load_prices
from investiq.ai.providers import AiProvider, AiProviderError, AnthropicProvider, strict_schema
from investiq.config import get_settings
from investiq.db.session import get_session
from investiq.models import AiRequest
from investiq.services.preferences import AiModelRoute, get_pref

log = logging.getLogger(__name__)
PROMPT_DIR = Path(__file__).parent / "prompts"
T = TypeVar("T", bound=BaseModel)
TIERS = ("low_cost", "premium", "reviewer")


class AiUnavailable(RuntimeError):
    """AI cannot run (no key, disabled, budget exhausted, unknown price). Callers degrade gracefully."""


@dataclass
class AiResult:
    output: BaseModel | None
    status: str  # ok, invalid_output, error, refusal, blocked_budget, unavailable
    request_id: int | None
    model: str
    prompt_version: str
    citations: CitationCheck | None
    error: str | None = None


def load_prompt(name: str) -> tuple[str, str]:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    m = re.search(r"<!-- version: ([\w.\-]+) -->", text)
    return text, (m.group(1) if m else f"{name}-unversioned")


class ModelRouter:
    def __init__(self, session: Session, *, provider_factory: Callable[[str], AiProvider] | None = None,
                 ledger_session_factory: Callable[[], Session] = get_session, cycle_id: int | None = None) -> None:
        self.session = session
        self.cycle_id = cycle_id
        self._provider_factory = provider_factory or self._default_provider
        self._ledger_factory = ledger_session_factory
        self._providers: dict[str, AiProvider] = {}
        self.models = get_pref(session, "ai_models")
        self.prices = load_prices()

    @staticmethod
    def _default_provider(name: str) -> AiProvider:
        if name == "anthropic":
            return AnthropicProvider(get_settings().secret("anthropic_api_key"))
        raise AiProviderError(f"unknown AI provider {name}")

    def route(self, tier: str) -> AiModelRoute:
        if tier not in TIERS:
            raise ValueError(tier)
        return getattr(self.models, tier)

    def available(self, tier: str) -> tuple[bool, str | None]:
        route = self.route(tier)
        if route.provider == "disabled":
            return False, f"{tier} AI is disabled in settings"
        if tier == "reviewer" and not self.models.reviewer_enabled:
            return False, "independent reviewer disabled"
        if route.provider == "anthropic" and not get_settings().secret("anthropic_api_key") and \
                self._provider_factory == self._default_provider:
            return False, "ANTHROPIC_API_KEY is not configured"
        st = budget.status(self.session)
        if st.paused or (tier == "premium" and st.premium_paused):
            return False, f"AI analysis paused: monthly budget reached ({st.spent_cad:.2f}/{st.limit_cad:.2f} CAD)"
        return True, None

    def run(self, *, task: str, role: str, tier: str, pack: EvidencePack, schema: type[T],
            extra_instructions: str = "") -> AiResult:
        route = self.route(tier)
        constitution, c_ver = load_prompt("constitution")
        role_prompt, r_ver = load_prompt(role)
        prompt_version = f"{c_ver}+{r_ver}"
        system = constitution + "\n\n" + role_prompt
        user = pack.render() + ("\n\n" + extra_instructions if extra_instructions else "") + \
            "\n\nRespond only with JSON matching the required schema."
        ok, why = self.available(tier)
        if not ok:
            return AiResult(None, "unavailable", None, route.model, prompt_version, None, why)
        try:
            price = self.prices.get(route.model)
        except UnknownModelPrice as exc:
            return AiResult(None, "unavailable", None, route.model, prompt_version, None, str(exc))

        ledger = self._ledger_factory()
        try:
            fx = budget.usd_cad(ledger)
            est_in = estimate_input_tokens(system + user)
            reserve_cad = price.cost_usd(est_in, route.max_output_tokens) * fx.rate
            req = AiRequest(cycle_id=self.cycle_id, task=task, role=role, tier=tier, provider=route.provider,
                            model=route.model, prompt_version=prompt_version, status="reserved",
                            usd_cad_rate=fx.rate, usd_cad_source=fx.source, pricing_version=self.prices.version,
                            budget_month=budget.budget_month())
            try:
                budget.reserve(ledger, amount_cad=reserve_cad, tier=tier, request=req)
            except budget.BudgetExceeded as exc:
                return AiResult(None, "blocked_budget", req.id, route.model, prompt_version, None, str(exc))

            try:
                provider = self._providers.get(route.provider) or self._provider_factory(route.provider)
                self._providers[route.provider] = provider
                completion = provider.complete(model=route.model, system=system, user=user,
                                               schema=strict_schema(schema.model_json_schema()),
                                               max_tokens=route.max_output_tokens, effort=route.effort)
            except AiProviderError as exc:
                req.error = str(exc)[:2000]
                budget.settle(ledger, req, status_="error", input_tokens=0, output_tokens=0, cost_usd=0.0,
                              usd_cad_rate=fx.rate)
                return AiResult(None, "error", req.id, route.model, prompt_version, None, str(exc))

            cost_usd = 0.0
            in_tok = out_tok = 0
            for part in completion.usage:
                try:
                    p = self.prices.get(part.model)
                except UnknownModelPrice:
                    p = self.prices.most_expensive()  # never under-count an unexpected model
                cost_usd += p.cost_usd(part.input_tokens, part.output_tokens)
                in_tok += part.input_tokens
                out_tok += part.output_tokens
            req.served_model = completion.served_model
            req.latency_ms = completion.latency_ms
            req.stop_reason = completion.stop_reason
            req.provider_request_id = completion.request_id

            if completion.stop_reason == "refusal":
                budget.settle(ledger, req, status_="refusal", input_tokens=in_tok, output_tokens=out_tok,
                              cost_usd=cost_usd, usd_cad_rate=fx.rate)
                return AiResult(None, "refusal", req.id, route.model, prompt_version, None, "model declined the request")
            try:
                if completion.stop_reason == "max_tokens":
                    raise ValueError("output truncated at max_tokens")
                parsed = schema.model_validate(json.loads(completion.text or ""))
            except (ValueError, ValidationError) as exc:
                req.error = f"invalid structured output: {exc}"[:2000]
                budget.settle(ledger, req, status_="invalid_output", input_tokens=in_tok, output_tokens=out_tok,
                              cost_usd=cost_usd, usd_cad_rate=fx.rate)
                return AiResult(None, "invalid_output", req.id, route.model, prompt_version, None, req.error)

            citations = check_citations(parsed, pack)
            status = "ok" if citations.acceptable else "invalid_output"
            if not citations.acceptable:
                req.error = (f"citation check failed: {len(citations.unsupported)}/{citations.total_claims} unsupported, "
                             f"invalid ids {citations.invalid_ids[:10]}")
            budget.settle(ledger, req, status_=status, input_tokens=in_tok, output_tokens=out_tok, cost_usd=cost_usd,
                          usd_cad_rate=fx.rate)
            return AiResult(parsed if status == "ok" else None, status, req.id, route.model, prompt_version, citations,
                            req.error)
        finally:
            ledger.close()
