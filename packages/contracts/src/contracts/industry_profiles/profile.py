"""
Industry analysis profile — the data contract for industry-aware research.

Adding a new industry means defining a new profile here (or in profiles.py)
and registering it. Agent code reads the profile at runtime; it does not
hard-code industry logic.
"""

from pydantic import BaseModel, Field

from ..enums import Capability, IndustryPlaybook, ValuationMethod


class RiskRuleSpec(BaseModel):
    """Deterministic risk flag derived from a computed metric."""

    id: str
    metric: str
    operator: str = Field(description="gt | lt | lte | gte")
    threshold: float
    severity: str = Field(description="high | medium | low")
    title: str
    why: str


class IndustryProfile(BaseModel):
    """Complete research strategy for one industry / business model."""

    profile_id: IndustryPlaybook
    display_name: str
    business_model: str

    required_financial_metrics: list[str] = Field(min_length=1)
    valuation_methods: list[ValuationMethod] = Field(min_length=1)
    key_performance_indicators: list[str] = Field(default_factory=list)
    business_risks: list[str] = Field(default_factory=list)
    competitive_factors: list[str] = Field(default_factory=list)
    investment_drivers: list[str] = Field(default_factory=list)

    required_capabilities: list[str] = Field(min_length=1)
    optional_capabilities: list[str] = Field(default_factory=list)
    risk_rules: list[RiskRuleSpec] = Field(default_factory=list)

    sector_matches: list[str] = Field(default_factory=list)
    industry_matches: list[str] = Field(default_factory=list)
    rationale: str = ""

    def task_payload(self) -> dict:
        """Serialize for A2A task inputs — agents load this instead of hard-coded logic."""
        return self.model_dump(mode="json")

    @property
    def required_metrics(self) -> list[str]:
        """Alias for ResearchPlan.required_metrics."""
        return self.required_financial_metrics


_UNIVERSAL = [
    Capability.COMPANY_PROFILE.value,
    Capability.FINANCIAL_STATEMENTS.value,
    Capability.FINANCIAL_RATIOS.value,
    Capability.NEWS_SENTIMENT.value,
    Capability.INVESTMENT_DRIVERS.value,
]
