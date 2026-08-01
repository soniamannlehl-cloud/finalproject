"""
Company Profile Agent.

Establishes what the business actually is: sector, industry, scale, and a
business description. Cheap, fast, and a dependency for competitor and risk
analysis, which cannot be meaningful without knowing what the company does.

Entirely deterministic -- no LLM call. The profile is retrieved facts, and
paraphrasing them through a model would add cost and hallucination risk
while subtracting attributability.
"""

import logging
from datetime import datetime, timezone

from contracts import Capability, Evidence, SourceType

from ..tools.yfinance_tool import get_company_profile

log = logging.getLogger(__name__)

AGENT_ID = "company_profile_agent"


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list]:
    ticker = (inputs or {}).get("ticker")
    if not ticker:
        raise ValueError("company.profile requires a 'ticker' input")

    profile = get_company_profile(ticker)

    # Confidence reflects completeness: a profile missing sector/industry is
    # usable but weaker, and the score should say so rather than claiming
    # certainty the data does not support.
    core_fields = ("name", "sector", "industry", "market_cap")
    completeness = sum(1 for k in core_fields if profile.get(k)) / len(core_fields)
    degraded = None if completeness == 1.0 else "profile missing some classification fields"

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.COMPANY_PROFILE, profile, run_id),
        run_id=run_id,
        task_id=task_id,
        agent_id=AGENT_ID,
        capability=Capability.COMPANY_PROFILE,
        source_type=SourceType.MARKET_DATA,
        source_name="Yahoo Finance",
        source_url=f"https://finance.yahoo.com/quote/{ticker}/profile",
        citation=f"Yahoo Finance company profile for {ticker}",
        content=profile,
        summary=(
            f"{profile.get('name')} -- {profile.get('industry') or 'industry n/a'} "
            f"in {profile.get('sector') or 'sector n/a'}"
        ),
        retrieved_at=datetime.now(timezone.utc),
        confidence=round(0.6 + 0.4 * completeness, 2),
        provider_degraded=degraded is not None,
    )

    return [evidence], evidence.confidence, degraded, []
