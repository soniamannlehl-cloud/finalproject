"""Tests for report section formatters."""

from contracts import StructuredThesis

from app.report.formatters import (
    clean_prose,
    format_business_overview,
    format_financial_analysis,
    format_investment_thesis,
    fmt_money,
)


def test_clean_prose_strips_claim_tags():
    text = "Strong margins [claim_abc123_interp] and growth."
    assert "[claim_" not in clean_prose(text)
    assert "Strong margins" in clean_prose(text)


def test_fmt_money_formats_billions():
    assert fmt_money(416_161_000_000) == "$416.16B"


def test_format_business_overview_includes_summary():
    html = format_business_overview([{
        "content": {
            "name": "Meta Platforms, Inc.",
            "ticker": "META",
            "sector": "Communication Services",
            "industry": "Internet Content & Information",
            "market_cap": 1_200_000_000_000,
            "employees": 70000,
            "summary": "Meta builds social and VR products.",
        },
    }])
    assert "Meta Platforms" in html
    assert "Business description" in html
    assert "social and VR" in html


def test_format_financial_analysis_renders_table():
    html = format_financial_analysis([
        {
            "capability": "financials.statements",
            "content": {
                "currency": "USD",
                "latest_period": "2025-09-27",
                "revenue": 416161000000,
                "net_income": 112010000000,
            },
        },
        {
            "capability": "financials.ratios",
            "content": {
                "metrics": {
                    "pe_ratio": {"name": "pe_ratio", "formatted": "41.24x", "meaningful": True},
                },
            },
        },
    ], [])
    assert "$416.16B" in html
    assert "41.24x" in html
    assert "data-table" in html


def test_format_investment_thesis_renders_framework_sections():
    fw = StructuredThesis(
        core_question="Should investors own Acme over the next 3-5 years?",
        primary_thesis="Strong revenue growth supports ownership.",
        supporting_drivers=["25% revenue growth", "Cheap vs peers"],
        key_risks=["Competition"],
        positive_catalysts=["Earnings beat"],
        negative_catalysts=["Regulatory risk"],
        valuation_opinion="cheap",
        confidence=0.75,
        missing_evidence=["None — required research capabilities satisfied"],
        recommendation="buy",
    )
    html = format_investment_thesis(fw)
    assert "Core question" in html
    assert "Primary investment thesis" in html
    assert "Supporting drivers" in html
    assert "Strong revenue growth" in html
    assert "Cheap" in html
    assert "75%" in html
