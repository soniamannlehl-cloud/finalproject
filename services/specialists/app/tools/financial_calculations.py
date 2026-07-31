"""
Deterministic financial calculations.

Every number the platform reports is produced here, in Python, never by an
LLM. This is a correctness requirement rather than a cost optimization: a
language model doing arithmetic is a defect, and the failure mode is a
confidently-stated wrong number that reads perfectly plausibly.

Each function returns a `Metric` carrying `meaningful` and `flag`, because
"not meaningful" is a real analytical answer. A negative-EPS company has no
meaningful P/E; reporting one anyway -- or silently omitting it -- both
mislead. Saying "not meaningful, because earnings are negative" is correct.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    """One computed value, or a documented reason it could not be computed."""

    name: str
    value: float | None
    formatted: str
    meaningful: bool = True
    flag: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "formatted": self.formatted,
            "meaningful": self.meaningful,
            "flag": self.flag,
        }


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def _mult(x: float) -> str:
    return f"{x:.2f}x"


def _money(x: float) -> str:
    for unit, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(x) >= scale:
            return f"${x / scale:.2f}{unit}"
    return f"${x:,.0f}"


def _na(name: str, reason: str) -> Metric:
    return Metric(name=name, value=None, formatted="n/a", meaningful=False, flag=reason)


# --- valuation --------------------------------------------------------------

def pe_ratio(price: float | None, eps: float | None) -> Metric:
    if price is None or eps is None:
        return _na("pe_ratio", "price or EPS unavailable")
    if eps <= 0:
        # The single most common way a naive screener produces nonsense.
        return _na("pe_ratio", "earnings are zero or negative -- P/E is not meaningful")
    return Metric("pe_ratio", price / eps, _mult(price / eps))


def price_to_book(price: float | None, book_value_per_share: float | None) -> Metric:
    if price is None or book_value_per_share is None:
        return _na("price_to_book", "price or book value unavailable")
    if book_value_per_share <= 0:
        return _na("price_to_book", "negative book value -- P/B is not meaningful")
    return Metric("price_to_book", price / book_value_per_share, _mult(price / book_value_per_share))


def ev_to_revenue(enterprise_value: float | None, revenue: float | None) -> Metric:
    if enterprise_value is None or not revenue:
        return _na("ev_to_revenue", "enterprise value or revenue unavailable")
    return Metric("ev_to_revenue", enterprise_value / revenue, _mult(enterprise_value / revenue))


def ev_to_ebitda(enterprise_value: float | None, ebitda: float | None) -> Metric:
    if enterprise_value is None or ebitda is None:
        return _na("ev_to_ebitda", "enterprise value or EBITDA unavailable")
    if ebitda <= 0:
        return _na("ev_to_ebitda", "negative EBITDA -- multiple is not meaningful")
    return Metric("ev_to_ebitda", enterprise_value / ebitda, _mult(enterprise_value / ebitda))


# --- profitability ----------------------------------------------------------

def gross_margin(gross_profit: float | None, revenue: float | None) -> Metric:
    if gross_profit is None or not revenue:
        return _na("gross_margin", "gross profit or revenue unavailable")
    return Metric("gross_margin", gross_profit / revenue, _pct(gross_profit / revenue))


def operating_margin(operating_income: float | None, revenue: float | None) -> Metric:
    if operating_income is None or not revenue:
        return _na("operating_margin", "operating income or revenue unavailable")
    return Metric("operating_margin", operating_income / revenue, _pct(operating_income / revenue))


def net_margin(net_income: float | None, revenue: float | None) -> Metric:
    if net_income is None or not revenue:
        return _na("net_margin", "net income or revenue unavailable")
    return Metric("net_margin", net_income / revenue, _pct(net_income / revenue))


def return_on_equity(net_income: float | None, equity: float | None) -> Metric:
    if net_income is None or not equity:
        return _na("return_on_equity", "net income or equity unavailable")
    if equity <= 0:
        return _na("return_on_equity", "negative equity -- ROE is not meaningful")
    return Metric("return_on_equity", net_income / equity, _pct(net_income / equity))


def return_on_assets(net_income: float | None, assets: float | None) -> Metric:
    if net_income is None or not assets:
        return _na("return_on_assets", "net income or total assets unavailable")
    return Metric("return_on_assets", net_income / assets, _pct(net_income / assets))


# --- growth -----------------------------------------------------------------

def revenue_growth(current: float | None, prior: float | None) -> Metric:
    if current is None or not prior:
        return _na("revenue_growth", "prior-period revenue unavailable")
    if prior < 0:
        return _na("revenue_growth", "negative prior-period base -- growth is not meaningful")
    return Metric("revenue_growth", (current - prior) / prior, _pct((current - prior) / prior))


# --- leverage & liquidity ---------------------------------------------------

def debt_to_equity(total_debt: float | None, equity: float | None) -> Metric:
    if total_debt is None or equity is None:
        return _na("debt_to_equity", "debt or equity unavailable")
    if equity <= 0:
        return _na("debt_to_equity", "negative equity -- D/E is not meaningful")
    return Metric("debt_to_equity", total_debt / equity, _mult(total_debt / equity))


def debt_to_ebitda(total_debt: float | None, ebitda: float | None) -> Metric:
    if total_debt is None or ebitda is None:
        return _na("debt_to_ebitda", "debt or EBITDA unavailable")
    if ebitda <= 0:
        return _na("debt_to_ebitda", "negative EBITDA -- leverage ratio is not meaningful")
    return Metric("debt_to_ebitda", total_debt / ebitda, _mult(total_debt / ebitda))


def current_ratio(current_assets: float | None, current_liabilities: float | None) -> Metric:
    if current_assets is None or not current_liabilities:
        return _na("current_ratio", "current assets or liabilities unavailable")
    return Metric(
        "current_ratio", current_assets / current_liabilities,
        _mult(current_assets / current_liabilities),
    )


# --- cash flow --------------------------------------------------------------

def free_cash_flow(operating_cash_flow: float | None, capex: float | None) -> Metric:
    if operating_cash_flow is None or capex is None:
        return _na("free_cash_flow", "operating cash flow or capex unavailable")
    value = operating_cash_flow - abs(capex)
    return Metric("free_cash_flow", value, _money(value))


def fcf_margin(fcf: float | None, revenue: float | None) -> Metric:
    if fcf is None or not revenue:
        return _na("fcf_margin", "free cash flow or revenue unavailable")
    return Metric("fcf_margin", fcf / revenue, _pct(fcf / revenue))


# --- composite --------------------------------------------------------------

def rule_of_40(revenue_growth_pct: float | None, fcf_margin_pct: float | None) -> Metric:
    """
    Software heuristic: growth% + FCF margin% should exceed 40.

    Encodes the actual tradeoff investors make for high-growth software --
    unprofitable growth and profitable stagnation can both be acceptable, but
    neither-nor is not.
    """
    if revenue_growth_pct is None or fcf_margin_pct is None:
        return _na("rule_of_40", "growth or FCF margin unavailable")
    score = (revenue_growth_pct + fcf_margin_pct) * 100
    return Metric(
        "rule_of_40", score, f"{score:.1f} ({'passes' if score >= 40 else 'below'} the 40 threshold)"
    )


def net_interest_margin(net_interest_income: float | None, earning_assets: float | None) -> Metric:
    """Bank-specific: the core spread business, meaningless outside lending."""
    if net_interest_income is None or not earning_assets:
        return _na("net_interest_margin", "net interest income or earning assets unavailable")
    return Metric(
        "net_interest_margin", net_interest_income / earning_assets,
        _pct(net_interest_income / earning_assets),
    )


def compute_all(financials: dict) -> dict[str, dict]:
    """
    Compute the standard metric set from a normalized financials dict.

    Missing inputs yield a flagged Metric rather than an omission, so the
    downstream interpreter can distinguish "we looked and it was negative"
    from "we never had the data".
    """
    f = financials
    revenue = f.get("revenue")

    fcf = free_cash_flow(f.get("operating_cash_flow"), f.get("capex"))
    growth = revenue_growth(revenue, f.get("revenue_prior"))
    fcf_m = fcf_margin(fcf.value, revenue)

    metrics = [
        pe_ratio(f.get("price"), f.get("eps")),
        price_to_book(f.get("price"), f.get("book_value_per_share")),
        ev_to_revenue(f.get("enterprise_value"), revenue),
        ev_to_ebitda(f.get("enterprise_value"), f.get("ebitda")),
        gross_margin(f.get("gross_profit"), revenue),
        operating_margin(f.get("operating_income"), revenue),
        net_margin(f.get("net_income"), revenue),
        return_on_equity(f.get("net_income"), f.get("total_equity")),
        return_on_assets(f.get("net_income"), f.get("total_assets")),
        growth,
        debt_to_equity(f.get("total_debt"), f.get("total_equity")),
        debt_to_ebitda(f.get("total_debt"), f.get("ebitda")),
        current_ratio(f.get("current_assets"), f.get("current_liabilities")),
        fcf,
        fcf_m,
        rule_of_40(growth.value, fcf_m.value),
    ]
    return {m.name: m.to_dict() for m in metrics}
