"""
Industry research playbooks.

This module is the answer to "the system must NOT use identical financial
analysis for every company." A bank and a REIT are not evaluated with the
same yardstick, and applying P/E to a REIT or inventory turnover to a bank
produces confident nonsense.

Each playbook declares:
  * which valuation methods actually mean something for the industry
  * which metrics a competent analyst would demand
  * which specialist capabilities the plan should request
  * which risks are worth probing for this business model

The Planner selects a playbook, then (when an LLM is available) refines the
selection and writes the rationale. The playbook itself stays deterministic
data, so industry coverage is reviewable and testable rather than being
re-derived by a language model on every run.
"""

from dataclasses import dataclass, field

from contracts import Capability, IndustryPlaybook, ValuationMethod


@dataclass(frozen=True)
class Playbook:
    """One industry's research strategy."""

    classification: IndustryPlaybook
    display_name: str

    valuation_methods: list[ValuationMethod]
    required_metrics: list[str]
    required_capabilities: list[str]
    optional_capabilities: list[str] = field(default_factory=list)

    key_risks: list[str] = field(default_factory=list)
    rationale: str = ""

    # yfinance sector/industry strings that select this playbook. Matched
    # case-insensitively as substrings, so "Banks - Regional" and
    # "Banks - Diversified" both hit the banking playbook.
    sector_matches: list[str] = field(default_factory=list)
    industry_matches: list[str] = field(default_factory=list)


# Capabilities every company gets regardless of industry.
_UNIVERSAL = [
    Capability.COMPANY_PROFILE.value,
    Capability.FINANCIAL_STATEMENTS.value,
    Capability.FINANCIAL_RATIOS.value,
    Capability.NEWS_SENTIMENT.value,
]


PLAYBOOKS: dict[IndustryPlaybook, Playbook] = {
    IndustryPlaybook.TECHNOLOGY: Playbook(
        classification=IndustryPlaybook.TECHNOLOGY,
        display_name="Technology / Software",
        valuation_methods=[
            ValuationMethod.EV_REVENUE,
            ValuationMethod.RULE_OF_40,
            ValuationMethod.EV_EBITDA,
        ],
        required_metrics=[
            "revenue_growth", "gross_margin", "rule_of_40",
            "rd_to_revenue", "operating_margin", "free_cash_flow",
        ],
        required_capabilities=_UNIVERSAL + [Capability.VALUATION.value],
        optional_capabilities=[
            Capability.COMPETITOR_ANALYSIS.value, Capability.EARNINGS_CALL.value
        ],
        key_risks=[
            "customer concentration",
            "competitive moat durability against larger platforms",
            "AI/technology disruption of the core product",
            "stock-based compensation diluting reported profitability",
        ],
        rationale=(
            "High-growth technology companies are valued on revenue multiples and "
            "growth-plus-margin composites rather than earnings, because reinvestment "
            "deliberately suppresses near-term profit. Rule of 40 balances growth "
            "against margin; P/E is often meaningless or negative."
        ),
        sector_matches=["technology"],
        industry_matches=["software", "semiconductor", "information technology", "internet"],
    ),
    IndustryPlaybook.BANKING: Playbook(
        classification=IndustryPlaybook.BANKING,
        display_name="Banking / Financial Services",
        valuation_methods=[ValuationMethod.PRICE_BOOK, ValuationMethod.PE_MULTIPLE],
        required_metrics=[
            "price_to_book", "return_on_equity", "return_on_assets",
            "net_interest_margin", "efficiency_ratio", "tier_1_capital_ratio",
        ],
        required_capabilities=_UNIVERSAL + [
            Capability.VALUATION.value, Capability.RISK_ANALYSIS.value
        ],
        optional_capabilities=[Capability.SEC_FILINGS.value],
        key_risks=[
            "credit quality and loan-loss provisioning",
            "interest-rate sensitivity of net interest margin",
            "regulatory capital requirements",
            "deposit flight / funding concentration",
        ],
        rationale=(
            "Banks are balance-sheet businesses: book value is the meaningful anchor, "
            "so price-to-book and ROE dominate. Revenue-based multiples and EBITDA are "
            "not meaningful because interest expense is an operating input, not financing."
        ),
        sector_matches=["financial services", "financial"],
        industry_matches=["bank", "credit services", "capital markets"],
    ),
    IndustryPlaybook.REIT: Playbook(
        classification=IndustryPlaybook.REIT,
        display_name="Real Estate Investment Trust",
        valuation_methods=[
            ValuationMethod.FFO_MULTIPLE, ValuationMethod.NAV, ValuationMethod.DCF
        ],
        required_metrics=[
            "ffo_per_share", "affo_per_share", "net_asset_value",
            "occupancy_rate", "dividend_yield", "debt_to_ebitda",
        ],
        required_capabilities=_UNIVERSAL + [Capability.VALUATION.value],
        optional_capabilities=[Capability.RISK_ANALYSIS.value],
        key_risks=[
            "interest-rate sensitivity of property valuations and refinancing",
            "occupancy and lease-expiry concentration",
            "tenant credit quality",
            "dividend sustainability relative to AFFO",
        ],
        rationale=(
            "REITs report large non-cash depreciation that makes net income and P/E "
            "misleading. FFO and AFFO add depreciation back to show actual cash "
            "generation; NAV anchors valuation to the underlying property portfolio."
        ),
        sector_matches=["real estate"],
        industry_matches=["reit", "real estate"],
    ),
    IndustryPlaybook.HEALTHCARE: Playbook(
        classification=IndustryPlaybook.HEALTHCARE,
        display_name="Healthcare / Pharmaceuticals",
        valuation_methods=[
            ValuationMethod.DCF, ValuationMethod.EV_EBITDA, ValuationMethod.EV_REVENUE
        ],
        required_metrics=[
            "rd_to_revenue", "gross_margin", "cash_runway_months",
            "revenue_growth", "operating_margin",
        ],
        required_capabilities=_UNIVERSAL + [
            Capability.RISK_ANALYSIS.value, Capability.SEC_FILINGS.value
        ],
        optional_capabilities=[
            Capability.VALUATION.value, Capability.COMPETITOR_ANALYSIS.value
        ],
        key_risks=[
            "clinical trial failure and pipeline concentration",
            "regulatory / FDA approval risk",
            "patent cliffs and generic erosion",
            "cash runway for pre-revenue biotech",
        ],
        rationale=(
            "Healthcare value is dominated by the pipeline and regulatory outcomes "
            "rather than current earnings. Pre-revenue biotech requires cash-runway "
            "analysis because solvency, not profitability, is the binding constraint."
        ),
        sector_matches=["healthcare"],
        industry_matches=["biotechnology", "drug", "pharmaceutical", "medical"],
    ),
    IndustryPlaybook.ENERGY: Playbook(
        classification=IndustryPlaybook.ENERGY,
        display_name="Energy / Natural Resources",
        valuation_methods=[
            ValuationMethod.EV_EBITDA, ValuationMethod.NAV, ValuationMethod.DCF
        ],
        required_metrics=[
            "ev_to_ebitda", "free_cash_flow", "debt_to_ebitda",
            "production_growth", "reserve_life", "dividend_yield",
        ],
        required_capabilities=_UNIVERSAL + [
            Capability.VALUATION.value, Capability.RISK_ANALYSIS.value
        ],
        optional_capabilities=[Capability.COMPETITOR_ANALYSIS.value],
        key_risks=[
            "commodity price exposure",
            "reserve replacement and depletion",
            "capital intensity and balance-sheet leverage through the cycle",
            "energy transition / stranded-asset risk",
        ],
        rationale=(
            "Energy earnings swing with commodity prices, so single-year P/E is "
            "misleading. EV/EBITDA and reserve-based NAV are more stable across the "
            "cycle, and leverage matters because the sector is capital intensive."
        ),
        sector_matches=["energy", "basic materials"],
        industry_matches=["oil", "gas", "coal", "mining", "uranium"],
    ),
    IndustryPlaybook.CONSUMER: Playbook(
        classification=IndustryPlaybook.CONSUMER,
        display_name="Consumer / Retail",
        valuation_methods=[
            ValuationMethod.PE_MULTIPLE, ValuationMethod.EV_EBITDA, ValuationMethod.DCF
        ],
        required_metrics=[
            "same_store_sales_growth", "gross_margin", "inventory_turnover",
            "operating_margin", "free_cash_flow",
        ],
        required_capabilities=_UNIVERSAL + [Capability.COMPETITOR_ANALYSIS.value],
        optional_capabilities=[Capability.VALUATION.value],
        key_risks=[
            "discretionary demand sensitivity to the consumer cycle",
            "inventory obsolescence and markdown risk",
            "brand relevance and channel shift to e-commerce",
            "input cost and freight inflation",
        ],
        rationale=(
            "Consumer businesses are judged on unit economics and same-store growth. "
            "Inventory turnover signals demand accuracy, and margins reveal pricing "
            "power against input inflation."
        ),
        sector_matches=["consumer cyclical", "consumer defensive"],
        industry_matches=["retail", "apparel", "restaurant", "beverage", "packaged food"],
    ),
    IndustryPlaybook.INDUSTRIAL: Playbook(
        classification=IndustryPlaybook.INDUSTRIAL,
        display_name="Industrials / Manufacturing",
        valuation_methods=[
            ValuationMethod.EV_EBITDA, ValuationMethod.PE_MULTIPLE, ValuationMethod.DCF
        ],
        required_metrics=[
            "operating_margin", "return_on_invested_capital", "backlog_growth",
            "free_cash_flow", "debt_to_ebitda",
        ],
        required_capabilities=_UNIVERSAL + [Capability.VALUATION.value],
        optional_capabilities=[Capability.COMPETITOR_ANALYSIS.value],
        key_risks=[
            "cyclical demand exposure",
            "input cost and supply-chain disruption",
            "capital intensity and fixed-cost operating leverage",
        ],
        rationale=(
            "Industrials are cyclical and capital intensive, so through-cycle margins, "
            "ROIC, and backlog matter more than a single year's earnings."
        ),
        sector_matches=["industrials"],
        industry_matches=["aerospace", "machinery", "construction", "transport", "defense"],
    ),
    IndustryPlaybook.UTILITIES: Playbook(
        classification=IndustryPlaybook.UTILITIES,
        display_name="Utilities",
        valuation_methods=[
            ValuationMethod.DCF, ValuationMethod.PE_MULTIPLE, ValuationMethod.PRICE_BOOK
        ],
        required_metrics=[
            "dividend_yield", "payout_ratio", "rate_base_growth",
            "debt_to_ebitda", "return_on_equity",
        ],
        required_capabilities=_UNIVERSAL + [Capability.RISK_ANALYSIS.value],
        optional_capabilities=[Capability.VALUATION.value],
        key_risks=[
            "regulatory rate-case outcomes",
            "interest-rate sensitivity given high leverage and bond-proxy status",
            "capital expenditure for grid modernization and decarbonization",
        ],
        rationale=(
            "Utilities are regulated, leveraged, income-oriented businesses. Value "
            "hinges on allowed returns and rate-base growth, and the equity trades as "
            "a bond proxy, so dividend safety and rate sensitivity dominate."
        ),
        sector_matches=["utilities"],
        industry_matches=["utility", "electric", "water"],
    ),
    IndustryPlaybook.GENERIC: Playbook(
        classification=IndustryPlaybook.GENERIC,
        display_name="General (industry-agnostic)",
        valuation_methods=[
            ValuationMethod.PE_MULTIPLE, ValuationMethod.EV_EBITDA, ValuationMethod.DCF
        ],
        required_metrics=[
            "revenue_growth", "gross_margin", "operating_margin",
            "free_cash_flow", "debt_to_equity",
        ],
        required_capabilities=_UNIVERSAL,
        optional_capabilities=[Capability.VALUATION.value],
        key_risks=["competitive position", "balance-sheet leverage", "demand cyclicality"],
        rationale=(
            "No industry-specific playbook matched, so a general framework is applied "
            "and this limitation is declared in the report rather than hidden."
        ),
        sector_matches=[],
        industry_matches=[],
    ),
}


def classify(sector: str | None, industry: str | None) -> tuple[IndustryPlaybook, str]:
    """
    Deterministically select a playbook from yfinance classification strings.

    Industry is checked before sector because it is more specific: a bank and
    an asset manager share the "Financial Services" sector but warrant
    different treatment. Returns the playbook and a human-readable reason so
    the choice is auditable.
    """
    industry_l = (industry or "").lower()
    sector_l = (sector or "").lower()

    for playbook in PLAYBOOKS.values():
        for token in playbook.industry_matches:
            if token in industry_l:
                return playbook.classification, f"industry '{industry}' matched '{token}'"

    for playbook in PLAYBOOKS.values():
        for token in playbook.sector_matches:
            if token in sector_l:
                return playbook.classification, f"sector '{sector}' matched '{token}'"

    return (
        IndustryPlaybook.GENERIC,
        f"no playbook matched sector={sector!r} industry={industry!r}; using general framework",
    )


def get_playbook(classification: IndustryPlaybook) -> Playbook:
    return PLAYBOOKS.get(classification, PLAYBOOKS[IndustryPlaybook.GENERIC])
