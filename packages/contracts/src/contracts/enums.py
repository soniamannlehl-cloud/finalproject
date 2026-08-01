"""
Shared enumerations.

These are string enums so they serialize cleanly across the A2A/HTTP
boundary and remain readable in LangSmith traces and database columns.
"""

from enum import StrEnum


class SourceType(StrEnum):
    """Where a piece of evidence came from. Drives freshness policy."""

    MARKET_DATA = "market_data"              # quotes, prices -- stale in minutes
    FINANCIAL_STATEMENT = "financial_statement"  # immutable once filed
    SEC_FILING = "sec_filing"                # immutable once filed
    NEWS = "news"                            # stale in days
    WEB_SEARCH = "web_search"                # stale in days
    ANALYST_ESTIMATE = "analyst_estimate"    # stale in weeks
    COMPUTED = "computed"                    # derived by our own deterministic code


class Criticality(StrEnum):
    """Whether a planned task must succeed for the run to be trustworthy."""

    REQUIRED = "required"    # failure reduces evidence_score and may block a recommendation
    OPTIONAL = "optional"    # failure is recorded as a declared gap only


class TaskState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"          # dependency failed, so this never ran
    DEGRADED = "degraded"        # completed via fallback provider / partial data


class Polarity(StrEnum):
    """Which side of the investment case a claim supports."""

    BULL = "bull"
    BEAR = "bear"
    NEUTRAL = "neutral"


class RecommendationAction(StrEnum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    # A first-class outcome, not an error: the system refuses to recommend
    # when evidence coverage or confidence falls below policy thresholds.
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class IndustryPlaybook(StrEnum):
    """
    Selects which metrics, valuation methods, and specialists the Planner
    uses. This is what stops every company from getting identical analysis.
    """

    TECHNOLOGY = "technology"
    BANKING = "banking"
    INSURANCE = "insurance"
    HEALTHCARE = "healthcare"
    ENERGY = "energy"
    RETAIL = "retail"
    MANUFACTURING = "manufacturing"
    CONSUMER_STAPLES = "consumer_staples"
    REIT = "reit"
    TELECOMMUNICATIONS = "telecommunications"
    INDUSTRIALS = "industrials"
    UTILITIES = "utilities"
    GENERIC = "generic"          # fallback when the industry isn't recognized


class ValuationMethod(StrEnum):
    DCF = "dcf"
    EV_REVENUE = "ev_revenue"
    EV_EBITDA = "ev_ebitda"
    PE_MULTIPLE = "pe_multiple"
    PRICE_BOOK = "price_book"          # banks
    FFO_MULTIPLE = "ffo_multiple"      # REITs
    NAV = "nav"                        # REITs, closed-end funds
    SUM_OF_PARTS = "sum_of_parts"
    RULE_OF_40 = "rule_of_40"          # software


class Severity(StrEnum):
    """Safety-check finding severity. BLOCKING stops a Buy/Sell recommendation."""

    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class ValidationStatus(StrEnum):
    """Outcome of company validation (HITL #1 gates on this)."""

    RESOLVED = "resolved"                # matched a public company
    PRIVATE_COMPANY = "private_company"  # real company, not publicly traded
    NOT_FOUND = "not_found"              # unrecognized input / likely typo
    AMBIGUOUS = "ambiguous"              # multiple plausible matches


class HumanDecision(StrEnum):
    """What a human chose at a HITL checkpoint."""

    CONFIRM = "confirm"                  # checkpoint 1
    REJECT_MATCH = "reject_match"        # checkpoint 1
    APPROVE = "approve"                  # checkpoint 2
    REJECT = "reject"                    # checkpoint 2
    REQUEST_ANALYSIS = "request_analysis"  # checkpoint 2 -> triggers replan


class Capability(StrEnum):
    """
    The A2A capability vocabulary.

    The Planner emits tasks naming a CAPABILITY; the Research Director
    resolves capability -> AgentCard -> endpoint at dispatch time. The
    Planner never names a concrete agent, which is what keeps the
    specialist fleet swappable without touching planning logic.
    """

    COMPANY_VALIDATE = "company.validate"
    COMPANY_PROFILE = "company.profile"
    FINANCIAL_STATEMENTS = "financials.statements"
    FINANCIAL_RATIOS = "financials.ratios"
    VALUATION = "valuation.estimate"
    COMPETITOR_ANALYSIS = "competitors.analysis"
    NEWS_SENTIMENT = "news.sentiment"
    SEC_FILINGS = "filings.sec"
    EARNINGS_CALL = "earnings.call"
    RISK_ANALYSIS = "risk.analysis"
    INVESTMENT_DRIVERS = "investment.drivers"
