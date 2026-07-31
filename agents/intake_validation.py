"""
agents/intake_validation.py

Intake & Validation Agent -- the first node in the investment research
graph. Resolves raw user text into a confirmed public ticker/company via
HITL Checkpoint #1, or explains why it couldn't (private company vs. not
found / typo).
"""

from typing import Optional

import yfinance as yf
from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from config import get_llm

PERSONA = (
    "You are a financial data specialist responsible for accurately "
    "identifying publicly traded companies from user descriptions."
)


def _search_ticker(raw_input: str) -> Optional[dict]:
    """
    Resolve raw_input to a public company/ticker via yfinance's search.
    Returns {"ticker", "company_name"} for the best EQUITY match, or None.
    """
    try:
        quotes = yf.Search(raw_input, max_results=5).quotes
    except Exception:
        quotes = []

    for q in quotes:
        symbol = q.get("symbol")
        name = q.get("shortname") or q.get("longname")
        if symbol and name and q.get("quoteType") == "EQUITY":
            return {"ticker": symbol, "company_name": name}
    return None


def _extract_company_candidate(raw_input: str) -> Optional[str]:
    """
    LLM extraction pre-step, used only when a direct search on raw_input
    finds nothing. Pulls a likely company name/ticker out of freeform
    phrasing (e.g. "the Delta situation" -> "Delta") so the search tool has
    something it can actually match against. Returns None if no plausible
    candidate can be identified.
    """
    llm = get_llm()
    prompt = (
        f"{PERSONA}\n\n"
        f'A user described a company like this: "{raw_input}"\n'
        "Extract ONLY the company name or ticker symbol they are referring to, "
        "with no extra words, quotes, or punctuation. If you cannot identify a "
        'specific company, respond with exactly "NONE".\n\nCompany name or ticker:'
    )
    response = llm.invoke(prompt)
    text = (response.content if hasattr(response, "content") else str(response)).strip()
    if not text or text.upper() == "NONE":
        return None
    return text


def _reason_about_no_match(raw_input: str) -> str:
    """
    No external tool -- pure LLM reasoning about whether raw_input names a
    real-but-private company, or is unrecognized/a typo.
    Returns "private_company" or "not_found".
    """
    llm = get_llm()
    prompt = (
        f"{PERSONA}\n\n"
        f'A user searched for a public company using this description: "{raw_input}"\n'
        "No matching publicly traded ticker was found.\n"
        "Reason about whether this most likely names a REAL company that is "
        "PRIVATELY held (not publicly traded), or whether the input is "
        "UNRECOGNIZED / likely a typo / not a real company name.\n"
        'Respond with exactly one word: "private" or "not_found".'
    )
    response = llm.invoke(prompt)
    text = (response.content if hasattr(response, "content") else str(response)).strip().lower()
    return "private_company" if "private" in text else "not_found"


def intake_validation_node(state: dict) -> dict:
    raw_input = (state.get("raw_user_input") or "").strip()
    match = _search_ticker(raw_input)

    if match is None:
        # Direct search on the raw text found nothing -- try an LLM-extracted
        # candidate before falling through to private/not-found classification
        # (handles freeform phrasing like "the Delta situation").
        candidate = _extract_company_candidate(raw_input)
        if candidate and candidate.lower() != raw_input.lower():
            match = _search_ticker(candidate)

    if match is None:
        status = _reason_about_no_match(raw_input)
        if status == "private_company":
            message = (
                f'"{raw_input}" looks like it could be a real company, but we could not find it '
                "on public markets -- it may be privately held. This tool can only research "
                "publicly traded companies. Try a different company name or ticker."
            )
        else:
            message = (
                f'We could not identify a publicly traded company from "{raw_input}". '
                'Try entering the full company name or its stock ticker symbol (e.g. "AAPL").'
            )
        return {
            "intake_status": status,
            "company_name": None,
            "ticker": None,
            "messages": [AIMessage(content=message)],
        }

    # Match found -- ALWAYS interrupt for confirmation (Checkpoint #1), every time.
    confirmation = interrupt({
        "type": "checkpoint_1_company_confirmation",
        "ticker": match["ticker"],
        "company_name": match["company_name"],
        "prompt": f"Did you mean {match['company_name']} ({match['ticker']})?",
    })

    confirmed = str(confirmation).strip().lower() in ("yes", "y", "true", "confirm", "confirmed")

    if confirmed:
        return {
            "intake_status": "confirmed",
            "company_name": match["company_name"],
            "ticker": match["ticker"],
            "checkpoint_1_approved": True,
            "messages": [AIMessage(
                content=f"Great -- researching {match['company_name']} ({match['ticker']})."
            )],
        }

    # No -> loop back to input (router sends this back to intake_validation_node)
    return {
        "intake_status": "pending",
        "company_name": None,
        "ticker": None,
        "checkpoint_1_approved": False,
        "messages": [AIMessage(
            content="No problem -- what company would you like to research instead?"
        )],
    }
