"""
tools/financial_calculations.py

Deterministic ratio calculations for the Financial Analyst Agent. One
function per ratio, each with div-by-zero/undefined guards. The LLM never
does this arithmetic itself -- it only interprets the results these
functions return.

`raw_financials` is a normalized flat dict (built by agents/financial_analyst.py
from whichever data source -- yfinance or Alpha Vantage -- actually returned
data), with these expected keys (any may be None if the source didn't report it):

    price, shares_outstanding, market_cap,
    net_income, eps, revenue, revenue_prior_year,
    gross_profit, operating_income, ebitda,
    total_debt, total_equity, total_equity_prior_year,
    total_assets, total_assets_prior_year,
    current_assets, current_liabilities, inventory,
    interest_expense, rd_expense, operating_expenses,
    dividends_paid, operating_cash_flow, capital_expenditures

Every function returns a dict:
    {
        "value": float | None,     # the raw computed number, or None if undefined
        "formatted": str,          # display-ready string, e.g. "24.3x", "12.4%"
        "meaningful": bool,        # False when the ratio should be flagged, not trusted
        "flag": str | None,        # short reason when meaningful is False
    }
"""

from typing import Optional


def _result(value: Optional[float], formatted: str, meaningful: bool = True, flag: Optional[str] = None) -> dict:
    return {"value": value, "formatted": formatted, "meaningful": meaningful, "flag": flag}


def _not_meaningful(reason: str) -> dict:
    return _result(None, "n/a", meaningful=False, flag=reason)


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _mult(x: float) -> str:
    return f"{x:.2f}x"


def _avg(current: Optional[float], prior: Optional[float]) -> Optional[float]:
    """Average two-period balance-sheet figures when both are available; else
    fall back to the single available figure (common when prior-period data
    wasn't returned by the source)."""
    if current is None and prior is None:
        return None
    if current is None:
        return prior
    if prior is None:
        return current
    return (current + prior) / 2


# ---------------------------------------------------------------------------
# Universal ratios -- computed for every company, every industry
# ---------------------------------------------------------------------------

def pe_ratio(f: dict) -> dict:
    price, eps = f.get("price"), f.get("eps")
    if price is None or eps is None:
        return _not_meaningful("Price or EPS not available")
    if eps <= 0:
        return _not_meaningful("Negative or zero earnings -- P/E is not meaningful")
    value = price / eps
    return _result(value, _mult(value))


def eps(f: dict) -> dict:
    value = f.get("eps")
    if value is None:
        return _not_meaningful("EPS not reported")
    return _result(value, f"${value:.2f}")


def pb_ratio(f: dict) -> dict:
    price = f.get("price")
    equity, shares = f.get("total_equity"), f.get("shares_outstanding")
    if price is None or equity is None or not shares:
        return _not_meaningful("Price, equity, or share count not available")
    if equity <= 0:
        return _not_meaningful("Negative shareholder equity -- P/B is not meaningful")
    book_value_per_share = equity / shares
    if book_value_per_share <= 0:
        return _not_meaningful("Non-positive book value per share")
    value = price / book_value_per_share
    return _result(value, _mult(value))


def revenue_growth(f: dict) -> dict:
    revenue, prior = f.get("revenue"), f.get("revenue_prior_year")
    if revenue is None or not prior:
        return _not_meaningful("Prior-year revenue not available")
    value = (revenue - prior) / prior
    return _result(value, _pct(value))


def gross_margin(f: dict) -> dict:
    gp, revenue = f.get("gross_profit"), f.get("revenue")
    if gp is None or not revenue:
        return _not_meaningful("Gross profit or revenue not available")
    value = gp / revenue
    return _result(value, _pct(value))


def operating_margin(f: dict) -> dict:
    op_income, revenue = f.get("operating_income"), f.get("revenue")
    if op_income is None or not revenue:
        return _not_meaningful("Operating income or revenue not available")
    value = op_income / revenue
    return _result(value, _pct(value))


def debt_to_equity(f: dict) -> dict:
    debt, equity = f.get("total_debt"), f.get("total_equity")
    if debt is None or equity is None:
        return _not_meaningful("Debt or equity not available")
    if equity <= 0:
        return _not_meaningful("Negative shareholder equity -- debt-to-equity is not meaningful")
    value = debt / equity
    return _result(value, _mult(value))


def free_cash_flow(f: dict) -> dict:
    ocf, capex = f.get("operating_cash_flow"), f.get("capital_expenditures")
    if ocf is None or capex is None:
        return _not_meaningful("Operating cash flow or capital expenditures not available")
    value = ocf - abs(capex)
    return _result(value, f"${value:,.0f}")


# ---------------------------------------------------------------------------
# Industry-specific ratios -- looked up per-company from data/industry_ratios.json
# ---------------------------------------------------------------------------

def return_on_equity(f: dict) -> dict:
    net_income = f.get("net_income")
    equity = _avg(f.get("total_equity"), f.get("total_equity_prior_year"))
    if net_income is None or not equity:
        return _not_meaningful("Net income or equity not available")
    if equity <= 0:
        return _not_meaningful("Negative shareholder equity -- ROE is not meaningful")
    value = net_income / equity
    return _result(value, _pct(value))


def return_on_assets(f: dict) -> dict:
    net_income = f.get("net_income")
    assets = _avg(f.get("total_assets"), f.get("total_assets_prior_year"))
    if net_income is None or not assets:
        return _not_meaningful("Net income or assets not available")
    value = net_income / assets
    return _result(value, _pct(value))


def efficiency_ratio(f: dict) -> dict:
    """Opex / revenue proxy. Not the precise bank regulatory efficiency ratio
    (noninterest expense / net revenue) since that breakdown isn't available
    from standard equity financial statements -- flagged as a proxy."""
    opex, revenue = f.get("operating_expenses"), f.get("revenue")
    if opex is None or not revenue:
        return _not_meaningful("Operating expenses or revenue not available")
    value = opex / revenue
    return _result(value, _pct(value))


def interest_coverage_ratio(f: dict) -> dict:
    op_income, interest = f.get("operating_income"), f.get("interest_expense")
    if op_income is None or not interest:
        return _not_meaningful("Interest expense not reported")
    value = op_income / interest
    return _result(value, _mult(value))


def current_ratio(f: dict) -> dict:
    ca, cl = f.get("current_assets"), f.get("current_liabilities")
    if ca is None or not cl:
        return _not_meaningful("Current assets or liabilities not available")
    value = ca / cl
    return _result(value, _mult(value))


def quick_ratio(f: dict) -> dict:
    ca, cl, inv = f.get("current_assets"), f.get("current_liabilities"), f.get("inventory")
    if ca is None or not cl:
        return _not_meaningful("Current assets or liabilities not available")
    inv = inv or 0
    value = (ca - inv) / cl
    return _result(value, _mult(value))


def asset_turnover(f: dict) -> dict:
    revenue = f.get("revenue")
    assets = _avg(f.get("total_assets"), f.get("total_assets_prior_year"))
    if revenue is None or not assets:
        return _not_meaningful("Revenue or assets not available")
    value = revenue / assets
    return _result(value, _mult(value))


def inventory_turnover(f: dict) -> dict:
    revenue, gp, inv = f.get("revenue"), f.get("gross_profit"), f.get("inventory")
    if revenue is None or gp is None or not inv:
        return _not_meaningful("Revenue, gross profit, or inventory not available")
    cogs = revenue - gp
    if cogs <= 0:
        return _not_meaningful("Cost of goods sold is non-positive")
    value = cogs / inv
    return _result(value, _mult(value))


def debt_to_ebitda(f: dict) -> dict:
    debt, ebitda_val = f.get("total_debt"), f.get("ebitda")
    if debt is None or ebitda_val is None:
        return _not_meaningful("Debt or EBITDA not available")
    if ebitda_val <= 0:
        return _not_meaningful("Negative EBITDA -- debt-to-EBITDA is not meaningful")
    value = debt / ebitda_val
    return _result(value, _mult(value))


def ebitda_margin(f: dict) -> dict:
    ebitda_val, revenue = f.get("ebitda"), f.get("revenue")
    if ebitda_val is None or not revenue:
        return _not_meaningful("EBITDA or revenue not available")
    value = ebitda_val / revenue
    return _result(value, _pct(value))


def rd_to_revenue(f: dict) -> dict:
    rd, revenue = f.get("rd_expense"), f.get("revenue")
    if rd is None:
        return _not_meaningful("R&D not separately reported")
    if not revenue:
        return _not_meaningful("Revenue not available")
    value = rd / revenue
    return _result(value, _pct(value))


def dividend_payout_ratio(f: dict) -> dict:
    dividends, net_income = f.get("dividends_paid"), f.get("net_income")
    if net_income is not None and net_income <= 0:
        return _not_meaningful("Negative earnings -- payout ratio is not meaningful")
    if not dividends:
        return _result(0.0, "0% (no dividends paid)")
    if not net_income:
        return _not_meaningful("Net income not available")
    value = abs(dividends) / net_income
    return _result(value, _pct(value))


def fcf_yield(f: dict) -> dict:
    fcf_result = free_cash_flow(f)
    market_cap = f.get("market_cap")
    if not fcf_result["meaningful"] or fcf_result["value"] is None:
        return _not_meaningful("Free cash flow not available")
    if not market_cap:
        return _not_meaningful("Market cap not available")
    value = fcf_result["value"] / market_cap
    return _result(value, _pct(value))


UNIVERSAL_REGISTRY = {
    "pe_ratio": pe_ratio,
    "eps": eps,
    "pb_ratio": pb_ratio,
    "revenue_growth": revenue_growth,
    "gross_margin": gross_margin,
    "operating_margin": operating_margin,
    "debt_to_equity": debt_to_equity,
    "free_cash_flow": free_cash_flow,
}

INDUSTRY_REGISTRY = {
    "return_on_equity": return_on_equity,
    "return_on_assets": return_on_assets,
    "efficiency_ratio": efficiency_ratio,
    "interest_coverage_ratio": interest_coverage_ratio,
    "current_ratio": current_ratio,
    "quick_ratio": quick_ratio,
    "asset_turnover": asset_turnover,
    "inventory_turnover": inventory_turnover,
    "debt_to_ebitda": debt_to_ebitda,
    "ebitda_margin": ebitda_margin,
    "rd_to_revenue": rd_to_revenue,
    "dividend_payout_ratio": dividend_payout_ratio,
    "fcf_yield": fcf_yield,
}


def compute_universal_ratios(raw_financials: dict) -> dict:
    """Always computed, every company, every industry."""
    return {name: fn(raw_financials) for name, fn in UNIVERSAL_REGISTRY.items()}


def compute_industry_ratios(raw_financials: dict, ratio_names: list) -> dict:
    """`ratio_names` comes from data/industry_ratios.json for this company's industry."""
    results = {}
    for name in ratio_names:
        fn = INDUSTRY_REGISTRY.get(name)
        if fn is None:
            results[name] = _not_meaningful(f"Unknown ratio '{name}'")
            continue
        results[name] = fn(raw_financials)
    return results
