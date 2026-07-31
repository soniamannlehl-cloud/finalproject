"""
Company Validation Agent.

Answers one question: does this user input name a company we can actually
research? Three outcomes, each of which the workflow handles differently:

  RESOLVED        -> candidates found; HITL #1 asks the human to confirm
  PRIVATE_COMPANY -> real company, not publicly traded; explain and stop
  NOT_FOUND       -> unrecognized or a typo; ask for a ticker or full name

The deterministic search runs first and answers most inputs for free. The
LLM is invoked only when search returns nothing, and only to make the
private-vs-typo judgment -- a genuinely semantic call that a lookup cannot
make. That ordering keeps the common path fast and cheap.
"""

import logging
from datetime import datetime, timezone

from contracts import Capability, Evidence, SourceType, ValidationStatus

from ..config import get_settings
from ..tools.yfinance_tool import CompanyMatch, ProviderError, search_companies

log = logging.getLogger(__name__)

AGENT_ID = "company_validation_agent"

_CLASSIFY_PROMPT = """You are a financial data specialist who identifies publicly traded companies.

A user searched for a company using this text: "{query}"
A search of public equity listings returned no match.

Decide which is more likely:
- The text names a REAL company that is PRIVATELY held (not publicly traded).
- The text is UNRECOGNIZED: a typo, a fictional name, or not a company at all.

Answer with exactly one word: PRIVATE or UNKNOWN"""


def _classify_no_match(query: str) -> tuple[ValidationStatus, str]:
    """
    Distinguish a private company from an unrecognized string.

    Falls back to NOT_FOUND whenever the LLM is unavailable or ambiguous:
    telling a user "we couldn't find that, try a ticker" is safe and
    actionable, whereas wrongly asserting a company is private is a
    confident falsehood.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return (
            ValidationStatus.NOT_FOUND,
            f'No public listing matched "{query}". Try the full company name or its ticker symbol.',
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.model_interpretation,
            temperature=0,
            max_tokens=5,
            messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(query=query)}],
        )
        verdict = (response.choices[0].message.content or "").strip().upper()
    except Exception as e:  # noqa: BLE001
        log.warning("validation classifier unavailable, defaulting to NOT_FOUND: %s", e)
        return (
            ValidationStatus.NOT_FOUND,
            f'No public listing matched "{query}". Try the full company name or its ticker symbol.',
        )

    if verdict.startswith("PRIVATE"):
        return (
            ValidationStatus.PRIVATE_COMPANY,
            f'"{query}" appears to be a real company, but we could not find it on public '
            "markets -- it may be privately held. This platform can only research publicly "
            "traded companies.",
        )
    return (
        ValidationStatus.NOT_FOUND,
        f'We could not identify a publicly traded company from "{query}". '
        "Try the full company name or its ticker symbol (for example, NVDA).",
    )


def _build_evidence(run_id: str, task_id: str, content: dict, confidence: float) -> Evidence:
    """Validation output is evidence like anything else -- attributable and timestamped."""
    return Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.COMPANY_VALIDATE, content),
        run_id=run_id,
        task_id=task_id,
        agent_id=AGENT_ID,
        capability=Capability.COMPANY_VALIDATE,
        source_type=SourceType.MARKET_DATA,
        source_name="Yahoo Finance",
        citation="Yahoo Finance equity listing search",
        content=content,
        summary=content.get("message"),
        retrieved_at=datetime.now(timezone.utc),
        confidence=confidence,
    )


def validate_company(query: str, run_id: str, task_id: str) -> tuple[Evidence, ValidationStatus]:
    """
    Resolve free text to candidate public companies.

    Returns (evidence, status). The caller wraps this into an A2ATaskResult;
    a provider outage surfaces as a raised ProviderError so the A2A layer can
    report FAILED rather than silently claiming "not found" -- conflating
    "we couldn't look" with "it doesn't exist" would be a data-integrity bug.
    """
    matches: list[CompanyMatch] = search_companies(query, max_results=10)

    if not matches:
        status, message = _classify_no_match(query)
        content = {
            "status": status.value,
            "query": query,
            "candidates": [],
            "message": message,
        }
        # High confidence in the search result itself; the private-vs-typo
        # judgment above it is a heuristic, hence not 1.0.
        return _build_evidence(run_id, task_id, content, 0.75), status

    top = matches[0]
    # An exact ticker match is unambiguous; a name match may not be.
    exact_ticker = top.ticker.upper() == query.strip().upper()
    confidence = 0.99 if exact_ticker else 0.85

    content = {
        "status": ValidationStatus.RESOLVED.value,
        "query": query,
        "candidates": [m.to_dict() for m in matches[:5]],
        "top_match": top.to_dict(),
        "exact_ticker_match": exact_ticker,
        "message": f"Found {top.name} ({top.ticker}) on {top.exchange}.",
    }
    return _build_evidence(run_id, task_id, content, confidence), ValidationStatus.RESOLVED


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list, float, str | None, list]:
    """
    A2A entrypoint for the `company.validate` capability.

    Returns the standard handler contract: (evidence, confidence,
    degraded_reason, claims). Raising here is intentional on provider
    failure -- the A2A server converts it into a FAILED task result, which
    the Director can retry.
    """
    query = (inputs or {}).get("query", "")
    if not query:
        raise ValueError("company.validate requires a non-empty 'query' input")

    try:
        evidence, _status = validate_company(query, run_id, task_id)
    except ProviderError:
        raise

    return [evidence], evidence.confidence, None, []
