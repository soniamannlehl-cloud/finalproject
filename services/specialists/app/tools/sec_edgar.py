"""
SEC EDGAR client.

The only genuinely primary source in the platform: filings are the legal
record a company is accountable for, not a vendor's interpretation of it.
Free and keyless, but the SEC requires a descriptive User-Agent identifying
the requester -- omitting it gets you blocked, so `SEC_USER_AGENT` is
configured rather than hardcoded.

The ticker->CIK map is a single ~1MB document covering every registrant, so
it is fetched once and cached process-wide rather than per request.
"""

import logging
import threading
from datetime import datetime, timezone

import httpx
from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import get_settings

log = logging.getLogger(__name__)

_CIK_MAP: dict[str, dict] | None = None
_CIK_LOCK = threading.Lock()

# Filing types worth surfacing. Deliberately excludes Forms 3/4/5 (insider
# transactions) and 13G/13D (ownership stakes), which dominate the recent
# feed by volume while saying little about the business itself.
MATERIAL_FORMS = {
    "10-K": "Annual report",
    "10-Q": "Quarterly report",
    "8-K": "Material event",
    "DEF 14A": "Proxy statement",
    "S-1": "Registration statement",
    "20-F": "Annual report (foreign issuer)",
    "40-F": "Annual report (Canadian issuer)",
}


class SECError(RuntimeError):
    """SEC EDGAR could not serve the request."""


def _headers() -> dict:
    return {
        "User-Agent": get_settings().sec_user_agent,
        "Accept-Encoding": "gzip, deflate",
    }


class SECPermanentError(SECError):
    """
    A failure that retrying cannot fix: a malformed User-Agent (403), or a
    company that simply has no filings (404).

    Separated from transient errors so the retry decorator doesn't burn three
    attempts and ~7 seconds on an outcome that is identical every time.
    """


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=8),
    # Only transient failures are worth retrying.
    retry=retry_if_not_exception_type(SECPermanentError),
    reraise=True,
)
def _get(url: str) -> dict:
    resp = httpx.get(url, headers=_headers(), timeout=get_settings().provider_timeout_s)

    if resp.status_code == 403:
        raise SECPermanentError(
            "SEC rejected the request (403). EDGAR requires a User-Agent identifying "
            "the requester with contact information, e.g. "
            "'Company Name contact@example.com'. Set SEC_USER_AGENT in .env."
        )
    if resp.status_code == 404:
        raise SECPermanentError(f"SEC has no record at {url}")

    resp.raise_for_status()
    return resp.json()


def _load_cik_map() -> dict[str, dict]:
    """Fetch and cache the full ticker->CIK registry (thread-safe, once per process)."""
    global _CIK_MAP
    if _CIK_MAP is not None:
        return _CIK_MAP

    with _CIK_LOCK:
        if _CIK_MAP is not None:  # another thread won the race
            return _CIK_MAP
        try:
            raw = _get("https://www.sec.gov/files/company_tickers.json")
        except Exception as e:  # noqa: BLE001
            raise SECError(f"could not load SEC ticker registry: {e}") from e

        _CIK_MAP = {
            entry["ticker"].upper(): {
                "cik": str(entry["cik_str"]).zfill(10),
                "title": entry["title"],
            }
            for entry in raw.values()
        }
        log.info("loaded SEC CIK map: %d registrants", len(_CIK_MAP))
        return _CIK_MAP


def resolve_cik(ticker: str) -> dict | None:
    """
    Map a ticker to its SEC CIK.

    Returns None for tickers with no SEC registration -- foreign listings and
    cross-listings legitimately have none, which is a declared gap rather
    than an error.
    """
    return _load_cik_map().get(ticker.upper())


def get_recent_filings(ticker: str, limit: int = 10) -> dict:
    """
    Recent material filings for a company.

    Filters to MATERIAL_FORMS so the result reflects business events rather
    than the insider-transaction noise that dominates the raw feed.
    """
    entry = resolve_cik(ticker)
    if entry is None:
        raise SECError(f"no SEC registration found for ticker {ticker!r}")

    cik = entry["cik"]
    try:
        data = _get(f"https://data.sec.gov/submissions/CIK{cik}.json")
    except Exception as e:  # noqa: BLE001
        raise SECError(f"SEC submissions unavailable for {ticker!r}: {e}") from e

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    filings = []
    for i, form in enumerate(forms):
        if form not in MATERIAL_FORMS or len(filings) >= limit:
            continue
        accession = accessions[i] if i < len(accessions) else ""
        filings.append({
            "form": form,
            "form_description": MATERIAL_FORMS[form],
            "filed_date": dates[i] if i < len(dates) else None,
            "accession_number": accession,
            "description": descriptions[i] if i < len(descriptions) else None,
            "url": (
                f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                f"{accession.replace('-', '')}/{docs[i]}"
                if accession and i < len(docs) else None
            ),
        })

    return {
        "ticker": ticker,
        "cik": cik,
        "registrant_name": data.get("name") or entry["title"],
        "sic_description": data.get("sicDescription"),
        "fiscal_year_end": data.get("fiscalYearEnd"),
        "state_of_incorporation": data.get("stateOfIncorporation"),
        "filings": filings,
        "filing_count": len(filings),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }


def get_company_facts(ticker: str, concepts: list[str] | None = None) -> dict:
    """
    Selected XBRL facts as filed.

    These are the numbers in the filing itself, which makes them stronger
    evidence than a data vendor's derived figures -- useful for
    corroborating (or contradicting) the market-data provider.
    """
    entry = resolve_cik(ticker)
    if entry is None:
        raise SECError(f"no SEC registration found for ticker {ticker!r}")

    concepts = concepts or ["Revenues", "NetIncomeLoss", "Assets", "StockholdersEquity"]

    try:
        data = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{entry['cik']}.json")
    except Exception as e:  # noqa: BLE001
        raise SECError(f"SEC company facts unavailable for {ticker!r}: {e}") from e

    us_gaap = data.get("facts", {}).get("us-gaap", {})
    facts = {}
    for concept in concepts:
        entries = us_gaap.get(concept, {}).get("units", {}).get("USD", [])
        annual = [e for e in entries if e.get("form") == "10-K" and e.get("fp") == "FY"]
        if not annual:
            continue
        latest = max(annual, key=lambda e: e.get("end", ""))
        facts[concept] = {
            "value": latest.get("val"),
            "period_end": latest.get("end"),
            "fiscal_year": latest.get("fy"),
            "form": latest.get("form"),
            "accession": latest.get("accn"),
        }

    return {
        "ticker": ticker,
        "cik": entry["cik"],
        "entity_name": data.get("entityName"),
        "facts": facts,
        "concepts_found": len(facts),
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
