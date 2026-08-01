"""
Industry profile definitions.

Each profile is pure configuration. The Planner selects one; specialists
consume it. To add a new industry, append a profile here and register it
in registry.py — no agent code changes required.
"""

from ..enums import Capability, IndustryPlaybook, ValuationMethod
from .profile import IndustryProfile, RiskRuleSpec, _UNIVERSAL

# Shared risk rules applied when metrics are computable
_LEVERAGE_RULE = RiskRuleSpec(
    id="high_leverage", metric="debt_to_ebitda", operator="gt", threshold=4.0,
    severity="high", title="Elevated financial leverage",
    why="Debt above 4x EBITDA limits flexibility and raises refinancing sensitivity.",
)
_NEGATIVE_FCF = RiskRuleSpec(
    id="negative_fcf", metric="free_cash_flow", operator="lt", threshold=0,
    severity="high", title="Negative free cash flow",
    why="The business consumes more cash than it generates.",
)

PROFILES: dict[IndustryPlaybook, IndustryProfile] = {
    IndustryPlaybook.TECHNOLOGY: IndustryProfile(
        profile_id=IndustryPlaybook.TECHNOLOGY,
        display_name="Technology / Software",
        business_model="Asset-light, high-growth software or hardware with reinvestment-heavy economics",
        required_financial_metrics=[
            "revenue_growth", "gross_margin", "operating_margin", "rule_of_40",
            "rd_to_revenue", "free_cash_flow", "fcf_margin",
        ],
        valuation_methods=[
            ValuationMethod.EV_REVENUE, ValuationMethod.RULE_OF_40, ValuationMethod.EV_EBITDA,
        ],
        key_performance_indicators=[
            "revenue_growth", "gross_margin", "rule_of_40", "rd_to_revenue", "net_revenue_retention",
        ],
        business_risks=[
            "customer concentration and platform dependency",
            "competitive moat durability against larger platforms",
            "AI/technology disruption of the core product",
            "stock-based compensation diluting reported profitability",
        ],
        competitive_factors=[
            "revenue_growth vs peers", "gross_margin vs peers", "ev_to_revenue vs peers",
            "rd_to_revenue vs peers",
        ],
        investment_drivers=[
            "sustained revenue growth and net retention",
            "margin expansion or Rule of 40 improvement",
            "platform adoption and ecosystem lock-in",
            "R&D efficiency translating to product velocity",
        ],
        required_capabilities=_UNIVERSAL + [Capability.VALUATION.value],
        optional_capabilities=[
            Capability.COMPETITOR_ANALYSIS.value, Capability.EARNINGS_CALL.value,
        ],
        risk_rules=[_NEGATIVE_FCF, RiskRuleSpec(
            id="rich_ev_revenue", metric="ev_to_revenue", operator="gt", threshold=15,
            severity="medium", title="Demanding revenue multiple",
            why="High EV/Revenue prices in substantial growth; misses tend to de-rate sharply.",
        )],
        sector_matches=["technology"],
        industry_matches=["software", "semiconductor", "information technology", "internet", "cloud"],
        rationale=(
            "High-growth technology companies are valued on revenue multiples and growth-plus-margin "
            "composites rather than earnings, because reinvestment deliberately suppresses near-term profit."
        ),
    ),
    IndustryPlaybook.BANKING: IndustryProfile(
        profile_id=IndustryPlaybook.BANKING,
        display_name="Banking / Financial Services",
        business_model="Balance-sheet lending and fee income; book value and ROE anchor valuation",
        required_financial_metrics=[
            "price_to_book", "return_on_equity", "return_on_assets",
            "net_interest_margin", "efficiency_ratio", "tier_1_capital_ratio",
        ],
        valuation_methods=[ValuationMethod.PRICE_BOOK, ValuationMethod.PE_MULTIPLE],
        key_performance_indicators=[
            "net_interest_margin", "return_on_equity", "efficiency_ratio", "loan_loss_provision",
        ],
        business_risks=[
            "credit quality and loan-loss provisioning",
            "interest-rate sensitivity of net interest margin",
            "regulatory capital requirements",
            "deposit flight / funding concentration",
        ],
        competitive_factors=[
            "price_to_book vs peers", "return_on_equity vs peers", "efficiency_ratio vs peers",
        ],
        investment_drivers=[
            "net interest margin expansion or stability",
            "credit quality and reserve adequacy",
            "capital return via dividends and buybacks",
            "efficiency ratio improvement",
        ],
        required_capabilities=_UNIVERSAL + [
            Capability.VALUATION.value, Capability.RISK_ANALYSIS.value,
        ],
        optional_capabilities=[Capability.SEC_FILINGS.value],
        risk_rules=[RiskRuleSpec(
            id="low_roe", metric="return_on_equity", operator="lt", threshold=0.08,
            severity="medium", title="Subpar return on equity",
            why="ROE below cost of equity suggests value destruction for shareholders.",
        )],
        sector_matches=["financial services", "financial"],
        industry_matches=["bank", "credit services", "capital markets"],
        rationale="Banks are balance-sheet businesses: book value and ROE dominate; revenue multiples are not meaningful.",
    ),
    IndustryPlaybook.INSURANCE: IndustryProfile(
        profile_id=IndustryPlaybook.INSURANCE,
        display_name="Insurance",
        business_model="Underwriting spread plus float investment; book value and combined ratio drive value",
        required_financial_metrics=[
            "price_to_book", "return_on_equity", "combined_ratio", "investment_yield",
            "loss_ratio", "expense_ratio",
        ],
        valuation_methods=[ValuationMethod.PRICE_BOOK, ValuationMethod.PE_MULTIPLE, ValuationMethod.DCF],
        key_performance_indicators=[
            "combined_ratio", "return_on_equity", "premium_growth", "investment_yield",
        ],
        business_risks=[
            "catastrophe and reserve adequacy",
            "underwriting cycle and pricing discipline",
            "investment portfolio mark-to-market sensitivity",
            "regulatory capital and rating agency constraints",
        ],
        competitive_factors=[
            "combined_ratio vs peers", "return_on_equity vs peers", "price_to_book vs peers",
        ],
        investment_drivers=[
            "combined ratio improvement below 100%",
            "premium growth in profitable lines",
            "reserve releases or favorable development",
            "investment income contribution",
        ],
        required_capabilities=_UNIVERSAL + [
            Capability.VALUATION.value, Capability.RISK_ANALYSIS.value,
        ],
        optional_capabilities=[Capability.SEC_FILINGS.value],
        risk_rules=[RiskRuleSpec(
            id="high_combined_ratio", metric="combined_ratio", operator="gt", threshold=100,
            severity="high", title="Underwriting losses",
            why="Combined ratio above 100% means underwriting operations lose money before investment income.",
        )],
        sector_matches=["financial services", "financial"],
        industry_matches=["insurance", "life insurance", "property", "reinsurance"],
        rationale="Insurers are valued on book value and underwriting discipline; combined ratio is the core KPI.",
    ),
    IndustryPlaybook.HEALTHCARE: IndustryProfile(
        profile_id=IndustryPlaybook.HEALTHCARE,
        display_name="Healthcare / Pharmaceuticals",
        business_model="Pipeline-driven; regulatory outcomes and R&D intensity dominate long-term value",
        required_financial_metrics=[
            "rd_to_revenue", "gross_margin", "cash_runway_months",
            "revenue_growth", "operating_margin", "free_cash_flow",
        ],
        valuation_methods=[
            ValuationMethod.DCF, ValuationMethod.EV_EBITDA, ValuationMethod.EV_REVENUE,
        ],
        key_performance_indicators=[
            "rd_to_revenue", "pipeline_progress", "cash_runway_months", "revenue_growth",
        ],
        business_risks=[
            "clinical trial failure and pipeline concentration",
            "regulatory / FDA approval risk",
            "patent cliffs and generic erosion",
            "cash runway for pre-revenue biotech",
        ],
        competitive_factors=[
            "gross_margin vs peers", "rd_to_revenue vs peers", "revenue_growth vs peers",
        ],
        investment_drivers=[
            "pipeline milestones and regulatory approvals",
            "R&D productivity and trial readouts",
            "patent estate durability",
            "commercial execution post-launch",
        ],
        required_capabilities=_UNIVERSAL + [
            Capability.RISK_ANALYSIS.value, Capability.SEC_FILINGS.value,
        ],
        optional_capabilities=[
            Capability.VALUATION.value, Capability.COMPETITOR_ANALYSIS.value,
        ],
        risk_rules=[_NEGATIVE_FCF, RiskRuleSpec(
            id="short_runway", metric="cash_runway_months", operator="lt", threshold=18,
            severity="high", title="Limited cash runway",
            why="Pre-profit biotech with under 18 months runway faces financing risk.",
        )],
        sector_matches=["healthcare"],
        industry_matches=["biotechnology", "drug", "pharmaceutical", "medical", "health"],
        rationale="Healthcare value is dominated by pipeline and regulatory outcomes rather than current earnings.",
    ),
    IndustryPlaybook.ENERGY: IndustryProfile(
        profile_id=IndustryPlaybook.ENERGY,
        display_name="Energy / Natural Resources",
        business_model="Commodity-linked production; cycle-normalized cash flow and reserve quality matter",
        required_financial_metrics=[
            "ev_to_ebitda", "free_cash_flow", "debt_to_ebitda",
            "production_growth", "reserve_life", "dividend_yield",
        ],
        valuation_methods=[
            ValuationMethod.EV_EBITDA, ValuationMethod.NAV, ValuationMethod.DCF,
        ],
        key_performance_indicators=[
            "production_growth", "reserve_replacement", "finding_costs", "leverage_through_cycle",
        ],
        business_risks=[
            "commodity price exposure",
            "reserve replacement and depletion",
            "capital intensity and balance-sheet leverage through the cycle",
            "energy transition / stranded-asset risk",
        ],
        competitive_factors=[
            "ev_to_ebitda vs peers", "production_cost vs peers", "debt_to_ebitda vs peers",
        ],
        investment_drivers=[
            "commodity price realization vs breakeven",
            "production volume growth",
            "reserve replacement at attractive finding costs",
            "capital discipline and shareholder returns",
        ],
        required_capabilities=_UNIVERSAL + [
            Capability.VALUATION.value, Capability.RISK_ANALYSIS.value,
        ],
        optional_capabilities=[Capability.COMPETITOR_ANALYSIS.value],
        risk_rules=[_LEVERAGE_RULE, _NEGATIVE_FCF],
        sector_matches=["energy", "basic materials"],
        industry_matches=["oil", "gas", "coal", "mining", "uranium", "exploration"],
        rationale="Energy earnings swing with commodity prices; EV/EBITDA and reserve-based NAV are more stable across the cycle.",
    ),
    IndustryPlaybook.RETAIL: IndustryProfile(
        profile_id=IndustryPlaybook.RETAIL,
        display_name="Retail / Consumer Discretionary",
        business_model="Unit economics and traffic-driven; same-store sales and inventory efficiency are critical",
        required_financial_metrics=[
            "same_store_sales_growth", "gross_margin", "inventory_turnover",
            "operating_margin", "free_cash_flow", "revenue_growth",
        ],
        valuation_methods=[
            ValuationMethod.PE_MULTIPLE, ValuationMethod.EV_EBITDA, ValuationMethod.DCF,
        ],
        key_performance_indicators=[
            "same_store_sales_growth", "inventory_turnover", "gross_margin", "traffic_trends",
        ],
        business_risks=[
            "discretionary demand sensitivity to the consumer cycle",
            "inventory obsolescence and markdown risk",
            "brand relevance and channel shift to e-commerce",
            "input cost and freight inflation",
        ],
        competitive_factors=[
            "same_store_sales_growth vs peers", "gross_margin vs peers", "inventory_turnover vs peers",
        ],
        investment_drivers=[
            "comp store sales acceleration",
            "margin recovery from pricing or mix",
            "inventory turns and working capital release",
            "omnichannel penetration and loyalty",
        ],
        required_capabilities=_UNIVERSAL + [Capability.COMPETITOR_ANALYSIS.value],
        optional_capabilities=[Capability.VALUATION.value],
        risk_rules=[
            RiskRuleSpec(
                id="revenue_decline", metric="revenue_growth", operator="lt", threshold=-0.05,
                severity="medium", title="Declining revenue",
                why="Revenue contraction pressures operating leverage in retail.",
            ),
            RiskRuleSpec(
                id="margin_pressure", metric="operating_margin", operator="lt", threshold=0,
                severity="high", title="Operating losses",
                why="Negative operating margin suggests unsustainable unit economics.",
            ),
        ],
        sector_matches=["consumer cyclical"],
        industry_matches=["retail", "apparel", "restaurant", "specialty retail", "department store"],
        rationale="Retail is judged on same-store growth and inventory turns; margins reveal pricing power against input inflation.",
    ),
    IndustryPlaybook.MANUFACTURING: IndustryProfile(
        profile_id=IndustryPlaybook.MANUFACTURING,
        display_name="Manufacturing",
        business_model="Capital-intensive production; throughput, yield, and ROIC drive returns",
        required_financial_metrics=[
            "operating_margin", "return_on_invested_capital", "asset_turnover",
            "inventory_turnover", "free_cash_flow", "debt_to_ebitda",
        ],
        valuation_methods=[
            ValuationMethod.EV_EBITDA, ValuationMethod.PE_MULTIPLE, ValuationMethod.DCF,
        ],
        key_performance_indicators=[
            "capacity_utilization", "yield_rates", "return_on_invested_capital", "backlog",
        ],
        business_risks=[
            "input cost volatility and supply-chain disruption",
            "capacity overbuild in downturns",
            "customer concentration in OEM supply chains",
            "automation capex requirements",
        ],
        competitive_factors=[
            "operating_margin vs peers", "return_on_invested_capital vs peers", "ev_to_ebitda vs peers",
        ],
        investment_drivers=[
            "volume recovery and utilization rates",
            "ROIC improvement from automation",
            "backlog conversion to revenue",
            "working capital efficiency",
        ],
        required_capabilities=_UNIVERSAL + [Capability.VALUATION.value],
        optional_capabilities=[Capability.COMPETITOR_ANALYSIS.value],
        risk_rules=[_LEVERAGE_RULE],
        sector_matches=["industrials", "basic materials"],
        industry_matches=["manufacturing", "auto parts", "steel", "chemicals", "packaging"],
        rationale="Manufacturers are judged on ROIC and utilization; capital intensity makes leverage and throughput critical.",
    ),
    IndustryPlaybook.CONSUMER_STAPLES: IndustryProfile(
        profile_id=IndustryPlaybook.CONSUMER_STAPLES,
        display_name="Consumer Staples",
        business_model="Defensive branded goods; pricing power, distribution, and dividend sustainability",
        required_financial_metrics=[
            "revenue_growth", "gross_margin", "operating_margin",
            "free_cash_flow", "dividend_yield", "payout_ratio",
        ],
        valuation_methods=[
            ValuationMethod.PE_MULTIPLE, ValuationMethod.EV_EBITDA, ValuationMethod.DCF,
        ],
        key_performance_indicators=[
            "organic_volume_growth", "pricing_power", "market_share", "dividend_coverage",
        ],
        business_risks=[
            "private label and retailer bargaining power",
            "input cost inflation without pricing pass-through",
            "brand erosion and shifting consumer preferences",
            "FX exposure in global portfolios",
        ],
        competitive_factors=[
            "gross_margin vs peers", "revenue_growth vs peers", "operating_margin vs peers",
        ],
        investment_drivers=[
            "pricing actions and volume mix",
            "cost savings and supply-chain efficiency",
            "brand reinvestment and innovation",
            "dividend growth sustainability",
        ],
        required_capabilities=_UNIVERSAL + [Capability.COMPETITOR_ANALYSIS.value],
        optional_capabilities=[Capability.VALUATION.value, Capability.RISK_ANALYSIS.value],
        risk_rules=[RiskRuleSpec(
            id="high_payout", metric="payout_ratio", operator="gt", threshold=0.85,
            severity="medium", title="Elevated dividend payout",
            why="Payout above 85% of earnings limits reinvestment and dividend safety.",
        )],
        sector_matches=["consumer defensive"],
        industry_matches=["packaged food", "beverage", "household", "personal products", "tobacco"],
        rationale="Staples investors prioritize stable cash flows, pricing power, and dividend reliability over growth.",
    ),
    IndustryPlaybook.REIT: IndustryProfile(
        profile_id=IndustryPlaybook.REIT,
        display_name="Real Estate Investment Trust (REIT)",
        business_model="Property portfolio with non-cash depreciation; FFO/AFFO and NAV anchor valuation",
        required_financial_metrics=[
            "ffo_per_share", "affo_per_share", "net_asset_value",
            "occupancy_rate", "dividend_yield", "debt_to_ebitda",
        ],
        valuation_methods=[
            ValuationMethod.FFO_MULTIPLE, ValuationMethod.NAV, ValuationMethod.DCF,
        ],
        key_performance_indicators=[
            "same_store_noi_growth", "occupancy_rate", "lease_spreads", "affo_payout_ratio",
        ],
        business_risks=[
            "interest-rate sensitivity of property valuations and refinancing",
            "occupancy and lease-expiry concentration",
            "tenant credit quality",
            "dividend sustainability relative to AFFO",
        ],
        competitive_factors=[
            "ffo_multiple vs peers", "occupancy_rate vs peers", "dividend_yield vs peers",
        ],
        investment_drivers=[
            "NOI growth and occupancy gains",
            "accretive acquisitions or development pipeline",
            "balance-sheet deleveraging",
            "AFFO dividend coverage",
        ],
        required_capabilities=_UNIVERSAL + [Capability.VALUATION.value],
        optional_capabilities=[Capability.RISK_ANALYSIS.value],
        risk_rules=[_LEVERAGE_RULE],
        sector_matches=["real estate"],
        industry_matches=["reit", "real estate"],
        rationale="REITs require FFO/AFFO and NAV; net income and P/E are misleading due to depreciation.",
    ),
    IndustryPlaybook.TELECOMMUNICATIONS: IndustryProfile(
        profile_id=IndustryPlaybook.TELECOMMUNICATIONS,
        display_name="Telecommunications",
        business_model="Infrastructure and subscription revenue; ARPU, churn, and capex intensity drive value",
        required_financial_metrics=[
            "ev_to_ebitda", "free_cash_flow", "dividend_yield",
            "revenue_growth", "debt_to_ebitda", "operating_margin",
        ],
        valuation_methods=[
            ValuationMethod.EV_EBITDA, ValuationMethod.DCF, ValuationMethod.PE_MULTIPLE,
        ],
        key_performance_indicators=[
            "arpu", "churn_rate", "subscriber_growth", "capex_to_sales",
        ],
        business_risks=[
            "competitive pricing and ARPU pressure",
            "heavy capex requirements for 5G/fiber buildout",
            "regulatory rate oversight",
            "high leverage and interest-rate sensitivity",
        ],
        competitive_factors=[
            "ev_to_ebitda vs peers", "subscriber_growth vs peers", "operating_margin vs peers",
        ],
        investment_drivers=[
            "subscriber net adds and churn improvement",
            "ARPU stabilization or growth",
            "capex peak and FCF inflection",
            "network quality and market share gains",
        ],
        required_capabilities=_UNIVERSAL + [
            Capability.VALUATION.value, Capability.RISK_ANALYSIS.value,
        ],
        optional_capabilities=[Capability.COMPETITOR_ANALYSIS.value],
        risk_rules=[_LEVERAGE_RULE, _NEGATIVE_FCF],
        sector_matches=["communication services"],
        industry_matches=["telecom", "wireless", "integrated telecom", "cable"],
        rationale="Telecom is valued on EBITDA and subscriber economics; capex cycles drive FCF inflection points.",
    ),
    IndustryPlaybook.INDUSTRIALS: IndustryProfile(
        profile_id=IndustryPlaybook.INDUSTRIALS,
        display_name="Industrials",
        business_model="Cyclical capital goods and services; backlog, ROIC, and through-cycle margins matter",
        required_financial_metrics=[
            "operating_margin", "return_on_invested_capital", "backlog_growth",
            "free_cash_flow", "debt_to_ebitda", "revenue_growth",
        ],
        valuation_methods=[
            ValuationMethod.EV_EBITDA, ValuationMethod.PE_MULTIPLE, ValuationMethod.DCF,
        ],
        key_performance_indicators=[
            "backlog_growth", "book_to_bill", "return_on_invested_capital", "aftermarket_mix",
        ],
        business_risks=[
            "cyclical demand exposure",
            "input cost and supply-chain disruption",
            "capital intensity and fixed-cost operating leverage",
        ],
        competitive_factors=[
            "operating_margin vs peers", "return_on_invested_capital vs peers", "ev_to_ebitda vs peers",
        ],
        investment_drivers=[
            "backlog conversion and book-to-bill above 1",
            "aftermarket and services mix expansion",
            "margin recovery through the cycle",
            "ROIC improvement from portfolio actions",
        ],
        required_capabilities=_UNIVERSAL + [Capability.VALUATION.value],
        optional_capabilities=[Capability.COMPETITOR_ANALYSIS.value],
        risk_rules=[_LEVERAGE_RULE],
        sector_matches=["industrials"],
        industry_matches=["aerospace", "machinery", "construction", "transport", "defense", "logistics"],
        rationale="Industrials are cyclical; through-cycle margins, ROIC, and backlog matter more than a single year's earnings.",
    ),
    IndustryPlaybook.UTILITIES: IndustryProfile(
        profile_id=IndustryPlaybook.UTILITIES,
        display_name="Utilities",
        business_model="Regulated returns on rate base; dividend yield and allowed ROE drive equity value",
        required_financial_metrics=[
            "dividend_yield", "payout_ratio", "rate_base_growth",
            "debt_to_ebitda", "return_on_equity", "operating_margin",
        ],
        valuation_methods=[
            ValuationMethod.DCF, ValuationMethod.PE_MULTIPLE, ValuationMethod.PRICE_BOOK,
        ],
        key_performance_indicators=[
            "rate_base_growth", "allowed_roe", "regulatory_lag", "dividend_coverage",
        ],
        business_risks=[
            "regulatory rate-case outcomes",
            "interest-rate sensitivity given high leverage",
            "capex for grid modernization and decarbonization",
        ],
        competitive_factors=[
            "dividend_yield vs peers", "return_on_equity vs peers", "payout_ratio vs peers",
        ],
        investment_drivers=[
            "rate-base growth from approved capex",
            "regulatory outcomes and allowed returns",
            "dividend growth sustainability",
            "decarbonization investment recovery",
        ],
        required_capabilities=_UNIVERSAL + [Capability.RISK_ANALYSIS.value],
        optional_capabilities=[Capability.VALUATION.value],
        risk_rules=[_LEVERAGE_RULE],
        sector_matches=["utilities"],
        industry_matches=["utility", "electric", "water", "gas utility"],
        rationale="Utilities are regulated, income-oriented businesses; dividend safety and rate-base growth dominate.",
    ),
    IndustryPlaybook.GENERIC: IndustryProfile(
        profile_id=IndustryPlaybook.GENERIC,
        display_name="General (industry-agnostic)",
        business_model="Diversified operating company without a matched industry profile",
        required_financial_metrics=[
            "revenue_growth", "gross_margin", "operating_margin",
            "free_cash_flow", "debt_to_equity", "return_on_equity",
        ],
        valuation_methods=[
            ValuationMethod.PE_MULTIPLE, ValuationMethod.EV_EBITDA, ValuationMethod.DCF,
        ],
        key_performance_indicators=["revenue_growth", "operating_margin", "free_cash_flow"],
        business_risks=["competitive position", "balance-sheet leverage", "demand cyclicality"],
        competitive_factors=["operating_margin vs peers", "revenue_growth vs peers", "ev_to_ebitda vs peers"],
        investment_drivers=["revenue growth", "margin expansion", "balance-sheet strength"],
        required_capabilities=_UNIVERSAL,
        optional_capabilities=[Capability.VALUATION.value],
        risk_rules=[_LEVERAGE_RULE, _NEGATIVE_FCF],
        sector_matches=[],
        industry_matches=[],
        rationale="No industry profile matched; a general framework is applied and this limitation is declared in the report.",
    ),
}
