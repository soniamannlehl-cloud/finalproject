"""
SEC Filings Agent.

Surfaces the primary regulatory record: what the company has told its
regulator, under legal accountability, rather than what a data vendor
inferred. Where filed XBRL facts disagree with market-data figures, that
disagreement is itself a finding -- the Contradiction Checker in M5 consumes
exactly this.

Fully deterministic. Filings are facts with dates and URLs; paraphrasing
them through a model would add cost and hallucination risk while subtracting
the attributability that makes them worth having.
"""

import logging
from datetime import datetime, timezone

from contracts import Capability, Evidence, SourceType

from ..tools.sec_edgar import SECError, get_company_facts, get_recent_filings

log = logging.getLogger(__name__)

AGENT_ID = "sec_filings_agent"


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list[Evidence], float, str | None, list]:
    ticker = (inputs or {}).get("ticker")
    if not ticker:
        raise ValueError("filings.sec requires a 'ticker' input")

    filings = get_recent_filings(ticker)

    # XBRL facts are a bonus, not a requirement: smaller registrants and
    # recent listings often have sparse tagging. Losing them degrades the
    # evidence rather than failing the task.
    facts, degraded = None, None
    try:
        facts = get_company_facts(ticker)
    except SECError as e:
        log.info("XBRL facts unavailable for %s: %s", ticker, e)
        degraded = "filed XBRL facts unavailable; filing index only"

    has_annual = any(f["form"] in ("10-K", "20-F", "40-F") for f in filings["filings"])
    if not has_annual:
        degraded = (degraded or "") + " no annual report in the recent filing window"

    content = {
        "ticker": ticker,
        "cik": filings["cik"],
        "registrant_name": filings["registrant_name"],
        "sic_description": filings.get("sic_description"),
        "fiscal_year_end": filings.get("fiscal_year_end"),
        "state_of_incorporation": filings.get("state_of_incorporation"),
        "recent_filings": filings["filings"],
        "filing_count": filings["filing_count"],
        "has_annual_report": has_annual,
        "filed_facts": facts["facts"] if facts else {},
    }

    # Confidence reflects what was actually retrieved, not what was requested.
    confidence = 0.95 if (has_annual and facts and facts["concepts_found"]) else 0.7

    evidence = Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.SEC_FILINGS, content, run_id),
        run_id=run_id, task_id=task_id, agent_id=AGENT_ID,
        capability=Capability.SEC_FILINGS,
        source_type=SourceType.SEC_FILING,
        source_name="SEC EDGAR",
        source_url=f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={filings['cik']}",
        citation=(
            f"SEC EDGAR filings for {filings['registrant_name']} "
            f"(CIK {filings['cik']}), {filings['filing_count']} recent material filing(s)"
        ),
        content=content,
        summary=(
            f"{filings['filing_count']} material filing(s); "
            f"{'annual report present' if has_annual else 'no recent annual report'}"
        ),
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
        provider_degraded=degraded is not None,
    )

    return [evidence], confidence, (degraded.strip() if degraded else None), []
