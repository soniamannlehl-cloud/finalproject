"""Turn structured evidence payloads into readable report prose (HTML fragments)."""

import html
import re
from typing import Any

from contracts import StructuredThesis

_CLAIM_TAG = re.compile(r"\[(?:claim|ev)_[a-f0-9]+(?:_\w+)?\]", re.I)
_CONVICTION_LINE = re.compile(r"\n*CONVICTION:\s*[\d.]+", re.I)


def clean_prose(text: str | None) -> str:
    if not text:
        return ""
    text = _CLAIM_TAG.sub("", text)
    text = _CONVICTION_LINE.sub("", text)
    return re.sub(r"\s{2,}", " ", text).strip()


def fmt_money(value: float | int | None, currency: str = "USD") -> str:
    if value is None:
        return "n/a"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    sym = "$" if currency.upper() in ("USD", "US") else f"{currency} "
    for unit, scale in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
        if abs(v) >= scale:
            return f"{sym}{v / scale:.2f}{unit}"
    return f"{sym}{v:,.0f}"


def fmt_pct(value: float | None, decimals: int = 1) -> str:
    if value is None:
        return "n/a"
    if abs(value) <= 1.0:
        return f"{value * 100:.{decimals}f}%"
    return f"{value:.{decimals}f}%"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f'<table class="data-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def format_business_overview(records: list[dict]) -> str:
    if not records:
        return "<p>No company profile was gathered for this run.</p>"

    profile = records[0].get("content") or {}
    if isinstance(profile, str):
        return f"<p>{html.escape(profile)}</p>"

    name = profile.get("name") or "Unknown"
    ticker = profile.get("ticker") or ""
    rows = [
        ["Sector", profile.get("sector") or "—"],
        ["Industry", profile.get("industry") or "—"],
        ["Exchange", profile.get("exchange") or "—"],
        ["Country", profile.get("country") or "—"],
        ["Market cap", fmt_money(profile.get("market_cap"))],
        ["Employees", f"{profile.get('employees'):,}" if profile.get("employees") else "—"],
        ["Website", profile.get("website") or "—"],
    ]
    parts = [f"<p><strong>{html.escape(name)}</strong> ({html.escape(ticker)})</p>"]
    parts.append(_table(["Field", "Value"], rows))

    summary = profile.get("summary")
    if summary:
        parts.append(f"<h3>Business description</h3><p>{html.escape(summary)}</p>")

    return "\n".join(parts)


def format_industry_analysis(
    industry: str | None,
    classification: str | None,
    profile_records: list[dict],
    competitor_records: list[dict],
) -> str:
    industry = industry or "Unknown"
    classification = classification or "generic"
    parts = [
        f"<p><strong>Industry:</strong> {html.escape(industry)}</p>",
        f"<p><strong>Analysis framework:</strong> {html.escape(classification.replace('_', ' '))}</p>",
    ]

    if profile_records:
        p = profile_records[0].get("content") or {}
        if p.get("sector"):
            parts.append(f"<p><strong>Sector:</strong> {html.escape(p['sector'])}</p>")

    if competitor_records:
        content = competitor_records[0].get("content") or {}
        peers = content.get("peers") or []
        peer_count = content.get("peer_count") or len(peers)
        if peers:
            rows = [[p.get("ticker", ""), p.get("name") or "—", fmt_pct(p.get("market_weight")) if p.get("market_weight") else "—"] for p in peers[:8]]
            parts.append("<h3>Industry peers (by market weight)</h3>")
            parts.append(_table(["Ticker", "Company", "Weight"], rows))
        elif peer_count == 0:
            parts.append(
                "<p><em>Peer set could not be resolved automatically for this industry. "
                "Valuation and competitive positioning may be limited.</em></p>"
            )
        comparison = content.get("comparison") or {}
        if comparison:
            rows = []
            for metric, data in comparison.items():
                if not isinstance(data, dict):
                    continue
                subj = data.get("subject")
                med = data.get("peer_median")
                pct = data.get("percentile_rank")
                if subj is None and med is None:
                    continue
                label = metric.replace("_", " ").title()
                rows.append([
                    label,
                    fmt_pct(subj) if metric.endswith("margin") or metric.endswith("growth") or metric == "return_on_equity" else (f"{subj:.2f}x" if subj is not None else "n/a"),
                    fmt_pct(med) if metric.endswith("margin") or metric.endswith("growth") or metric == "return_on_equity" else (f"{med:.2f}x" if med is not None else "n/a"),
                    f"{int(pct * 100)}th pct." if pct is not None else "—",
                ])
            if rows:
                parts.append("<h3>Peer-relative positioning</h3>")
                parts.append(_table(["Metric", "Company", "Peer median", "Percentile"], rows))

    return "\n".join(parts)


def format_financial_analysis(records: list[dict], claims: list[dict]) -> str:
    parts: list[str] = []
    statements = next((r for r in records if r.get("capability") == "financials.statements"), None)
    ratios = next((r for r in records if r.get("capability") == "financials.ratios"), None)

    if statements:
        fin = statements.get("content") or {}
        currency = fin.get("currency") or "USD"
        period = fin.get("latest_period") or "latest"
        rows = [
            ["Revenue", fmt_money(fin.get("revenue"), currency)],
            ["Net income", fmt_money(fin.get("net_income"), currency)],
            ["EBITDA", fmt_money(fin.get("ebitda"), currency)],
            ["Operating cash flow", fmt_money(fin.get("operating_cash_flow"), currency)],
            ["Total debt", fmt_money(fin.get("total_debt"), currency)],
            ["Total equity", fmt_money(fin.get("total_equity"), currency)],
            ["Market cap", fmt_money(fin.get("market_cap"), currency)],
            ["Share price", fmt_money(fin.get("price"), currency)],
        ]
        parts.append(f"<h3>Reported financials ({html.escape(str(period))})</h3>")
        parts.append(_table(["Item", "Value"], rows))

    if ratios:
        content = ratios.get("content") or {}
        metrics = content.get("metrics") or {}
        if metrics:
            rows = []
            for _key, m in metrics.items():
                if not isinstance(m, dict):
                    continue
                name = m.get("name", _key).replace("_", " ").title()
                if m.get("meaningful"):
                    rows.append([name, m.get("formatted", "n/a"), ""])
                else:
                    rows.append([name, "n/a", m.get("flag") or "not meaningful"])
            parts.append("<h3>Key ratios &amp; metrics</h3>")
            parts.append(_table(["Metric", "Value", "Note"], rows))

    fin_claims = [c for c in claims if c.get("category") == "financial"]
    if fin_claims:
        parts.append("<h3>Analyst interpretation</h3>")
        parts.append(f"<p>{html.escape(clean_prose(fin_claims[0].get('text', '')))}</p>")

    if not parts:
        return "<p>No financial data was gathered for this run.</p>"
    return "\n".join(parts)


def format_valuation(records: list[dict]) -> str:
    if not records:
        return "<p>No valuation analysis was performed.</p>"

    content = records[0].get("content") or {}
    parts: list[str] = []
    vr = content.get("valuation_range")
    current = content.get("current_price")

    if vr:
        parts.append(
            f"<p><strong>Implied equity value range:</strong> "
            f"{fmt_money(vr.get('low'))} – {fmt_money(vr.get('high'))} per share "
            f"(midpoint {fmt_money(vr.get('midpoint'))}) vs current {fmt_money(current)}.</p>"
        )
        if vr.get("vs_current_pct") is not None:
            parts.append(f"<p>Midpoint vs current price: <strong>{vr['vs_current_pct']:+.1f}%</strong></p>")
    else:
        parts.append("<p>Could not compute an implied valuation range with available peer data.</p>")

    results = content.get("results") or []
    if results:
        rows = []
        for r in results:
            if not r.get("applicable"):
                rows.append([r.get("label", r.get("method", "")), "N/A", r.get("reason", "not applicable")])
            else:
                rows.append([
                    r.get("label", ""),
                    fmt_money(r.get("implied_price_per_share")),
                    f"Peer median {r.get('peer_median_multiple')}x on {r.get('driver')}",
                ])
        parts.append(_table(["Method", "Implied price/share", "Basis"], rows))

    unsupported = content.get("unsupported_methods") or []
    if unsupported:
        parts.append("<h3>Methods not applied</h3><ul>")
        for u in unsupported:
            parts.append(f"<li>{html.escape(u.get('method', ''))}: {html.escape(u.get('reason', ''))}</li>")
        parts.append("</ul>")

    parts.append(
        f"<p><em>Based on {content.get('peer_count', 0)} industry peer(s); "
        f"{len([r for r in results if r.get('applicable')])} method(s) produced estimates.</em></p>"
    )
    return "\n".join(parts)


def format_competitive_analysis(records: list[dict]) -> str:
    if not records:
        return "<p>No competitive analysis was performed.</p>"
    content = records[0].get("content") or {}
    industry = content.get("industry") or "Unknown"
    parts = [f"<p><strong>Industry:</strong> {html.escape(str(industry))}</p>"]

    peers = content.get("peers") or []
    if peers:
        rows = [[p.get("ticker", ""), p.get("name") or "—"] for p in peers[:8]]
        parts.append("<h3>Peer group</h3>")
        parts.append(_table(["Ticker", "Company"], rows))

    comparison = content.get("comparison") or {}
    if comparison:
        rows = []
        for metric, data in comparison.items():
            if not isinstance(data, dict):
                continue
            subj = data.get("subject")
            med = data.get("peer_median")
            vs = data.get("vs_median")
            if subj is None and med is None:
                continue
            is_ratio = "margin" in metric or "growth" in metric or metric == "return_on_equity"
            rows.append([
                metric.replace("_", " ").title(),
                fmt_pct(subj) if is_ratio else (f"{subj:.2f}x" if subj is not None else "n/a"),
                fmt_pct(med) if is_ratio else (f"{med:.2f}x" if med is not None else "n/a"),
                f"{vs:+.2f}" if vs is not None and not is_ratio else (fmt_pct(vs) if vs is not None else "—"),
            ])
        if rows:
            parts.append("<h3>Metrics vs peer median</h3>")
            parts.append(_table(["Metric", "Company", "Peer median", "Difference"], rows))
    elif content.get("peer_count", 0) == 0:
        parts.append("<p><em>No peer group could be resolved for comparison.</em></p>")

    return "\n".join(parts)


def format_news(records: list[dict], claims: list[dict]) -> str:
    parts: list[str] = []
    if records:
        content = records[0].get("content") or {}
        articles = content.get("articles") or []
        tone = content.get("tone") or content.get("sentiment_summary") or records[0].get("summary", "")
        count = content.get("article_count") or len(articles)
        parts.append(
            f"<p><strong>Coverage:</strong> {count} article(s) in the last "
            f"{content.get('lookback_days', 30)} days · <strong>Tone:</strong> {html.escape(str(tone))}</p>"
        )
        if articles:
            parts.append("<h3>Recent headlines</h3><ul>")
            for a in articles[:10]:
                title = a.get("title") or a.get("headline") or "Untitled"
                src = a.get("source") or a.get("publisher") or ""
                parts.append(f"<li>{html.escape(str(title))} <em>({html.escape(str(src))})</em></li>")
            parts.append("</ul>")

    news_claims = [c for c in claims if c.get("category") in ("news", "sentiment")]
    if news_claims:
        parts.append(f"<p>{html.escape(clean_prose(news_claims[0].get('text', '')))}</p>")

    return "\n".join(parts) if parts else "<p>No news data gathered.</p>"


def format_earnings(records: list[dict]) -> str:
    if not records:
        return "<p>No earnings history was gathered.</p>"
    content = records[0].get("content") or {}
    beats = content.get("beats")
    misses = content.get("misses")
    quarters = content.get("quarters_analyzed")
    parts = [
        f"<p><strong>Earnings track record:</strong> {beats or 0} beat(s), {misses or 0} miss(es) "
        f"over {quarters or 'recent'} quarter(s).</p>",
    ]
    note = content.get("transcript_note")
    if note:
        parts.append(f"<p><em>{html.escape(note)}</em></p>")

    history = content.get("earnings_history") or []
    rows = []
    for q in history[:8]:
        if isinstance(q, dict):
            rows.append([
                str(q.get("period") or q.get("date") or q.get("quarter") or "—"),
                str(q.get("eps_actual") or q.get("actual") or "—"),
                str(q.get("eps_estimate") or q.get("estimate") or "—"),
                str(q.get("surprise_pct") or q.get("surprise") or q.get("result") or "—"),
            ])
    if rows:
        parts.append(_table(["Period", "Actual EPS", "Estimate", "Surprise"], rows))
    return "\n".join(parts)


def format_evidence_section(records: list[dict], claims: list[dict], empty: str) -> str:
    if not records:
        return f"<p>{html.escape(empty)}</p>"
    parts = []
    for r in records[:3]:
        summary = r.get("summary") or ""
        if summary:
            parts.append(f"<p>{html.escape(summary)}</p>")
    return "\n".join(parts) if parts else f"<p>{html.escape(empty)}</p>"


_VALUATION_DISPLAY = {
    "cheap": "Cheap",
    "fair": "Fair",
    "expensive": "Expensive",
    "insufficient_data": "Insufficient data",
}


def format_investment_thesis(framework: StructuredThesis) -> str:
    """Render the analyst investment thesis framework as HTML."""
    val_label = _VALUATION_DISPLAY.get(framework.valuation_opinion, framework.valuation_opinion)
    rec = framework.recommendation.replace("_", " ").title()

    def _list(items: list[str]) -> str:
        if not items:
            return "<p>None identified.</p>"
        return "<ul>" + "".join(f"<li>{html.escape(clean_prose(i))}</li>" for i in items) + "</ul>"

    return f"""
<div class="thesis-framework">
  <h3>Core question ({html.escape(framework.horizon)})</h3>
  <p><strong>{html.escape(framework.core_question)}</strong></p>

  <h3>Primary investment thesis</h3>
  <p>{html.escape(clean_prose(framework.primary_thesis))}</p>

  <h3>Supporting drivers</h3>
  {_list(framework.supporting_drivers)}

  <h3>Key risks</h3>
  {_list(framework.key_risks)}

  <h3>Catalysts</h3>
  <p><strong>Positive</strong></p>
  {_list(framework.positive_catalysts)}
  <p><strong>Negative</strong></p>
  {_list(framework.negative_catalysts)}

  <h3>Valuation opinion</h3>
  <p><strong>{html.escape(val_label)}</strong></p>

  <h3>Confidence</h3>
  <p>{framework.confidence:.0%}</p>

  <h3>Missing evidence</h3>
  {_list(framework.missing_evidence)}

  <h3>Recommendation</h3>
  <p><strong>{html.escape(rec)}</strong></p>
</div>
""".strip()


def format_investment_drivers(records: list[dict], industry_profile: dict | None) -> str:
    """Render industry-specific investment driver assessment."""
    if not records:
        profile_name = (industry_profile or {}).get("display_name", "selected industry")
        return f"<p>No investment driver analysis was run for the {html.escape(profile_name)} profile.</p>"

    content = records[0].get("content") or {}
    drivers = content.get("investment_drivers") or (industry_profile or {}).get("investment_drivers") or []
    assessments = content.get("kpi_assessments") or []
    summary = content.get("summary")

    parts = []
    if drivers:
        parts.append("<h3>Industry investment drivers</h3><ul>")
        parts.extend(f"<li>{html.escape(d)}</li>" for d in drivers)
        parts.append("</ul>")

    if assessments:
        rows = []
        for a in assessments:
            rows.append([
                a.get("kpi", "—"),
                a.get("status", "—"),
                clean_prose(a.get("detail", "")),
            ])
        parts.append("<h3>KPI assessment</h3>")
        parts.append(_table(["KPI", "Status", "Detail"], rows))

    if summary:
        parts.append(f"<h3>Summary</h3><p>{html.escape(clean_prose(summary))}</p>")

    return "\n".join(parts) if parts else "<p>No driver data available.</p>"
