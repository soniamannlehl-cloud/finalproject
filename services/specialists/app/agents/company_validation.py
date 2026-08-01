"""
Company Validation Agent.

Answers one question: does this user input name a company we can actually
research? Three outcomes, each of which the workflow handles differently:

  RESOLVED        -> candidates found; HITL #1 asks the human to confirm
  PRIVATE_COMPANY -> real company, not publicly traded; explain and stop
  NOT_FOUND       -> unrecognized or a typo; ask for a ticker or full name

The deterministic search runs first and answers most inputs for free. When
the match is unclear or missing, an LLM suggests likely corrections (e.g.
"micrft" -> Microsoft). That keeps typos from silently researching the
wrong company.
"""

import logging
import re
from difflib import SequenceMatcher
from datetime import datetime, timezone

from contracts import Capability, Evidence, SourceType, ValidationStatus

from ..config import get_settings
from ..tools.yfinance_tool import CompanyMatch, ProviderError, search_companies

log = logging.getLogger(__name__)

AGENT_ID = "company_validation_agent"

# Below this, the query is too far from the match name/ticker to auto-confirm.
_CLEAR_MATCH_THRESHOLD = 0.82

_CLASSIFY_PROMPT = """You are a financial data specialist who identifies publicly traded companies.

A user searched for a company using this text: "{query}"
A search of public equity listings returned no clear match.

Decide which is more likely:
- The text names a REAL company that is PRIVATELY held (not publicly traded).
- The text is UNRECOGNIZED: a typo, a fictional name, or not a company at all.

Answer with exactly one word: PRIVATE or UNKNOWN"""

_SUGGEST_PROMPT = """A user searched for a publicly traded company using: "{query}"
The lookup did not find a clear match — this is probably a typo.

If you can identify the likely public company they meant, reply exactly:
SUGGEST:TICKER:Full Company Name

Examples:
- micrft -> SUGGEST:MSFT:Microsoft Corporation
- nvdia -> SUGGEST:NVDA:NVIDIA Corporation

If the text names a real private company (not publicly traded), reply: PRIVATE
If you cannot identify a likely public company, reply: NONE"""


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _similarity(a: str, b: str) -> float:
    a_norm, b_norm = _normalize(a), _normalize(b)
    if not a_norm or not b_norm:
        return 0.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def _match_score(query: str, match: CompanyMatch) -> float:
    """How closely the user input matches one search candidate."""
    name = match.name or ""
    first_word = name.split()[0] if name else ""
    return max(
        _similarity(query, match.ticker),
        _similarity(query, name),
        _similarity(query, first_word) if first_word else 0.0,
    )


def _is_clear_match(query: str, match: CompanyMatch) -> bool:
    """
    True when the user clearly meant this company — exact ticker, substring
    of the name, or very high string similarity.
    """
    q = query.strip()
    if match.ticker.upper() == q.upper():
        return True

    q_lower = q.lower()
    name_lower = (match.name or "").lower()
    if name_lower and (q_lower in name_lower or name_lower.startswith(q_lower)):
        return True

    return _match_score(q, match) >= _CLEAR_MATCH_THRESHOLD


def _llm_suggest_company(query: str) -> dict | None:
    """
    Ask the LLM what public company the user probably meant.

    Returns {"ticker": ..., "name": ...} or None. Verified suggestions only —
    we re-search the ticker before surfacing it.
    """
    settings = get_settings()
    if not settings.openai_api_key:
        return None

    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.model_interpretation,
            temperature=0,
            max_tokens=40,
            messages=[{"role": "user", "content": _SUGGEST_PROMPT.format(query=query)}],
        )
        verdict = (response.choices[0].message.content or "").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("validation suggestion unavailable: %s", e)
        return None

    if verdict.upper().startswith("PRIVATE"):
        return None

    if verdict.upper().startswith("SUGGEST:"):
        parts = verdict.split(":", 2)
        if len(parts) >= 3:
            ticker, name = parts[1].strip().upper(), parts[2].strip()
            if ticker and name:
                return {"ticker": ticker, "name": name}

    return None


def _verify_suggestion(suggestion: dict) -> CompanyMatch | None:
    """Confirm a suggested ticker exists on public markets."""
    ticker = suggestion.get("ticker", "")
    if not ticker:
        return None
    matches = search_companies(ticker, max_results=3)
    if not matches:
        return None
    exact = next((m for m in matches if m.ticker.upper() == ticker.upper()), matches[0])
    return exact


def _classify_no_match(query: str) -> tuple[ValidationStatus, str, dict | None]:
    """
    Distinguish a private company from an unrecognized string.

    Falls back to NOT_FOUND whenever the LLM is unavailable or ambiguous.
    """
    suggestion = _llm_suggest_company(query)
    verified = _verify_suggestion(suggestion) if suggestion else None

    settings = get_settings()
    if not settings.openai_api_key and not verified:
        return (
            ValidationStatus.NOT_FOUND,
            f'No public listing matched "{query}". Try the full company name or its ticker symbol.',
            None,
        )

    if verified:
        return (
            ValidationStatus.NOT_FOUND,
            f'We couldn\'t find a company matching "{query}". '
            f"Did you mean {verified.name} ({verified.ticker})?",
            verified.to_dict(),
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
            None,
        )

    if verdict.startswith("PRIVATE"):
        return (
            ValidationStatus.PRIVATE_COMPANY,
            f'"{query}" appears to be a real company, but we could not find it on public '
            "markets — it may be privately held. This platform can only research publicly "
            "traded companies.",
            None,
        )

    return (
        ValidationStatus.NOT_FOUND,
        f'We could not identify a publicly traded company from "{query}". '
        "Try the full company name or its ticker symbol (for example, NVDA).",
        None,
    )


def _not_found_for_typo(
    query: str, verified: CompanyMatch, run_id: str, task_id: str
) -> tuple[Evidence, ValidationStatus]:
    message = (
        f'We couldn\'t find a company matching "{query}". '
        f"Did you mean {verified.name} ({verified.ticker})?"
    )
    content = {
        "status": ValidationStatus.NOT_FOUND.value,
        "query": query,
        "candidates": [],
        "suggested_match": verified.to_dict(),
        "message": message,
    }
    return _build_evidence(run_id, task_id, content, 0.8), ValidationStatus.NOT_FOUND


def _build_evidence(run_id: str, task_id: str, content: dict, confidence: float) -> Evidence:
    """Validation output is evidence like anything else — attributable and timestamped."""
    return Evidence(
        evidence_id=Evidence.make_id(AGENT_ID, Capability.COMPANY_VALIDATE, content, run_id),
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
    report FAILED rather than silently claiming "not found".
    """
    query = (query or "").strip()
    matches: list[CompanyMatch] = search_companies(query, max_results=10)

    if matches:
        exact_ticker = next((m for m in matches if m.ticker.upper() == query.upper()), None)
        if exact_ticker:
            return _resolved(query, matches, exact_ticker, exact_match=True, run_id=run_id, task_id=task_id)

        clear_matches = [m for m in matches if _is_clear_match(query, m)]
        if clear_matches:
            return _resolved(query, matches, clear_matches[0], exact_match=False, run_id=run_id, task_id=task_id)

        # Search returned something, but nothing close enough — likely a typo.
        suggestion = _llm_suggest_company(query)
        verified = _verify_suggestion(suggestion) if suggestion else None
        if not verified:
            best = max(matches, key=lambda m: _match_score(query, m))
            if _match_score(query, best) >= 0.55:
                verified = best

        if verified and not _is_clear_match(query, verified):
            return _not_found_for_typo(query, verified, run_id, task_id)

    status, message, suggested = _classify_no_match(query)
    content = {
        "status": status.value,
        "query": query,
        "candidates": [],
        "message": message,
    }
    if suggested:
        content["suggested_match"] = suggested
    return _build_evidence(run_id, task_id, content, 0.75), status


def _resolved(
    query: str,
    matches: list[CompanyMatch],
    top: CompanyMatch,
    *,
    exact_match: bool,
    run_id: str,
    task_id: str,
) -> tuple[Evidence, ValidationStatus]:
    confidence = 0.99 if exact_match else 0.85
    content = {
        "status": ValidationStatus.RESOLVED.value,
        "query": query,
        "candidates": [m.to_dict() for m in matches[:5]],
        "top_match": top.to_dict(),
        "exact_ticker_match": exact_match,
        "message": f"Found {top.name} ({top.ticker}) on {top.exchange}.",
    }
    return _build_evidence(run_id, task_id, content, confidence), ValidationStatus.RESOLVED


def handle(inputs: dict, run_id: str, task_id: str) -> tuple[list, float, str | None, list]:
    """
    A2A entrypoint for the `company.validate` capability.

    Returns the standard handler contract: (evidence, confidence,
    degraded_reason, claims). Raising here is intentional on provider
    failure — the A2A server converts it into a FAILED task result, which
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
