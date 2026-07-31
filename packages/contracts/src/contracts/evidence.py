"""
Evidence and Claim -- the backbone of the platform's guardrail system.

The central rule: no downstream agent may state a fact it did not receive
as Evidence. A Claim cannot be constructed without at least one supporting
evidence_id, so "every statement must cite evidence" is enforced by the
type system rather than by asking an LLM to behave.
"""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from pydantic import BaseModel, Field, field_validator

from .enums import Polarity, SourceType

# How long evidence of each type stays trustworthy. Used by the deterministic
# freshness check -- no LLM involved, because this is arithmetic on timestamps.
# Filings and reported statements are immutable once published, so they never
# go stale in the "might have changed" sense.
FRESHNESS_POLICY: dict[SourceType, timedelta | None] = {
    SourceType.MARKET_DATA: timedelta(hours=24),
    SourceType.NEWS: timedelta(days=14),
    SourceType.WEB_SEARCH: timedelta(days=30),
    SourceType.ANALYST_ESTIMATE: timedelta(days=90),
    SourceType.FINANCIAL_STATEMENT: None,   # immutable once reported
    SourceType.SEC_FILING: None,            # immutable once filed
    SourceType.COMPUTED: None,              # derived from other evidence
}


class Evidence(BaseModel):
    """
    One immutable, attributable fact retrieved by a specialist agent.

    Evidence is written once and never mutated. Downstream agents reference
    it by `evidence_id`; the full record lives in Postgres so that LangGraph
    state stays small enough to checkpoint cheaply on every superstep.
    """

    evidence_id: str = Field(description="Stable content-derived ID; see make_id()")
    run_id: str
    task_id: str
    agent_id: str = Field(description="Which specialist produced this")
    capability: str = Field(description="Which A2A capability was being served")

    source_type: SourceType
    source_name: str = Field(description="Human-readable provider, e.g. 'SEC EDGAR'")
    source_url: str | None = None
    citation: str = Field(description="Render-ready citation string for the report")

    content: dict = Field(description="Structured payload -- never free prose")
    summary: str | None = Field(default=None, description="Optional one-line gloss")

    as_of_date: datetime | None = Field(
        default=None, description="When the DATA is from (e.g. fiscal period end)"
    )
    retrieved_at: datetime = Field(description="When WE fetched it")

    confidence: float = Field(ge=0.0, le=1.0)
    provider_degraded: bool = Field(
        default=False,
        description="True if served by a fallback provider or partial response",
    )

    @field_validator("retrieved_at", "as_of_date")
    @classmethod
    def _require_timezone(cls, v: datetime | None) -> datetime | None:
        """Naive datetimes silently break freshness math across services."""
        if v is not None and v.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware")
        return v

    @staticmethod
    def make_id(agent_id: str, capability: str, content: dict) -> str:
        """
        Deterministic content-addressed ID.

        Identical content from the same agent+capability yields the same ID,
        which gives us free deduplication when a retry re-fetches unchanged
        data, and makes cached runs reproducible.
        """
        payload = json.dumps(
            {"agent": agent_id, "cap": capability, "content": content},
            sort_keys=True,
            default=str,
        )
        return "ev_" + hashlib.sha256(payload.encode()).hexdigest()[:16]

    def age(self, now: datetime | None = None) -> timedelta:
        """How long ago this was retrieved."""
        now = now or datetime.now(timezone.utc)
        return now - self.retrieved_at

    def is_stale(self, now: datetime | None = None) -> bool:
        """
        Deterministic freshness check driven by FRESHNESS_POLICY.

        Deliberately not an LLM call: this is timestamp arithmetic, where a
        language model can only introduce error.
        """
        limit = FRESHNESS_POLICY.get(self.source_type)
        if limit is None:
            return False
        return self.age(now) > limit


class Claim(BaseModel):
    """
    An interpretive statement derived from evidence.

    `evidence_ids` is constrained to be non-empty, so an uncited claim is
    unconstructible. Downstream, the Evidence Validator additionally checks
    that each referenced ID actually resolves in the repository -- together
    these close the loop on fabricated citations.
    """

    claim_id: str
    run_id: str
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(
        min_length=1,
        description="Non-empty by construction -- the anti-fabrication guardrail",
    )
    confidence: float = Field(ge=0.0, le=1.0)
    polarity: Polarity = Polarity.NEUTRAL
    category: str = Field(description="e.g. 'financial', 'risk', 'valuation'")
    author_agent_id: str
    created_at: datetime

    @field_validator("evidence_ids")
    @classmethod
    def _no_duplicates(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("evidence_ids must not contain duplicates")
        return v
