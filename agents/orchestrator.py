"""
agents/orchestrator.py

Orchestrator Agent -- synthesizes the 3 specialists' research into a
beginner-friendly memo, with explicit, inspectable planning/reasoning steps.
Owns HITL Checkpoint #2 (memo review + open-ended Q&A) and dispatches
follow-up questions via the A2A router to the specific owning specialist.

CRITICAL PRODUCT PRINCIPLE: never issues a buy/sell/hold recommendation.
May classify the evidence pattern descriptively (e.g. "fits a growth-style
profile"), never as personalized advice, never based on a stored user
profile -- no persistent user profile exists anywhere in this system.
"""

from langgraph.types import interrupt

from config import get_llm
from tools.a2a_router import route_question, send_message

PERSONA = (
    "You are a senior research analyst who synthesizes specialist research "
    "into clear, evidence-based investment memos -- presenting patterns in "
    "the evidence without issuing investment recommendations."
)


def _llm_text(response) -> str:
    return (response.content if hasattr(response, "content") else str(response)).strip()


def _parse_bullets(text: str) -> list:
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-") or stripped.startswith("*") or stripped.startswith("•"):
            items.append(stripped.lstrip("-*•").strip())
    return items


def _specialist_context(state: dict) -> str:
    parts = []

    if state.get("sentiment_failed"):
        parts.append("SENTIMENT: unavailable -- this specialist's research failed.")
    else:
        parts.append(
            "SENTIMENT:\n"
            f"  summary: {state.get('sentiment_summary')}\n"
            f"  trend: {state.get('sentiment_trend')}"
        )

    if state.get("financial_failed"):
        parts.append("FINANCIAL: unavailable -- this specialist's research failed.")
    else:
        parts.append(
            "FINANCIAL:\n"
            f"  interpretation: {state.get('ratio_interpretation')}"
        )

    if state.get("macro_failed"):
        parts.append("MACRO/INDUSTRY: unavailable -- this specialist's research failed.")
    else:
        landscape = state.get("industry_landscape") or {}
        parts.append(
            "MACRO/INDUSTRY:\n"
            f"  interpretation: {state.get('macro_interpretation')}\n"
            f"  competitive landscape: {landscape.get('competitive_summary')}"
        )

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Explicit planning / task decomposition -- 4 separate LLM calls so each
# sub-step is its own inspectable span in LangSmith traces, not one opaque
# call that hides the reasoning.
# ---------------------------------------------------------------------------

def _step1_evidence_pattern(company_name: str, context: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 1 of 4 -- identify the evidence pattern.\n\n"
        f"Company: {company_name}\n\n{context}\n\n"
        "Classify the overall EVIDENCE PATTERN this research fits (e.g. \"fits a growth-style "
        "profile\", \"fits a value-style profile\", \"turnaround story\", \"mixed/inconclusive "
        "signals\"). This is a DESCRIPTIVE classification of the evidence only -- NEVER a "
        "buy/sell/hold recommendation, and never personalized to any individual user (no user "
        "profile exists in this system). Respond in 1-2 sentences."
    )
    return _llm_text(llm.invoke(prompt))


def _step2_risk_factors(company_name: str, context: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 2 of 4 -- identify risk factors.\n\n"
        f"Company: {company_name}\n\n{context}\n\n"
        "Identify the 2-3 MOST decision-relevant risk factors for THIS SPECIFIC company based on "
        "the research above -- not a generic template list. List each as a bullet point starting "
        "with '-', one sentence each, plain language."
    )
    return _llm_text(llm.invoke(prompt))


def _step3_invalidation_triggers(company_name: str, context: str, step1: str, step2: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 3 of 4 -- identify invalidation triggers.\n\n"
        f"Company: {company_name}\n\n{context}\n\n"
        f"Evidence pattern identified in step 1: {step1}\n"
        f"Risk factors identified in step 2: {step2}\n\n"
        "Identify 2-3 specific, observable events or data points that would INVALIDATE the "
        "evidence pattern above -- things a beginner investor could actually watch for. List "
        "each as a bullet point starting with '-', one sentence each, plain language."
    )
    return _llm_text(llm.invoke(prompt))


def _step4_catalysts_timeline(company_name: str, context: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 4 of 4 -- identify catalysts and timeline.\n\n"
        f"Company: {company_name}\n\n{context}\n\n"
        "Identify near-term catalysts (upcoming events, earnings dates, industry developments) "
        "that could move the evidence pattern in either direction, and a rough timeline for each. "
        "2-3 bullet points starting with '-', plain language."
    )
    return _llm_text(llm.invoke(prompt))


# ---------------------------------------------------------------------------
# Final synthesis -- beginner-friendly memo style (CRITICAL, enforced here)
# ---------------------------------------------------------------------------

def _synthesize_memo(company_name: str, ticker: str, context: str, reasoning_chain: list, llm) -> dict:
    reasoning_text = "\n\n".join(f"{step['step']}: {step['output']}" for step in reasoning_chain)
    prompt = (
        f"{PERSONA}\n\n"
        f"Company: {company_name} ({ticker})\n\n"
        f"Specialist research:\n{context}\n\n"
        f"Your own prior reasoning:\n{reasoning_text}\n\n"
        "Write the memo for a BEGINNER INVESTOR WITH NO FINANCE BACKGROUND. Rules, no exceptions:\n"
        "- Every technical term gets a plain-language gloss the FIRST time it appears (not just "
        "\"P/E ratio: 24\" -- explain what that means in the same sentence).\n"
        "- State the headline finding in ONE plain sentence, with no jargon, before any detail.\n"
        "- In each section, give the plain-language takeaway FIRST, supporting numbers/evidence AFTER.\n"
        "- Never issue a buy/sell/hold recommendation anywhere.\n\n"
        "Respond in exactly this format:\n"
        "HEADLINE: <one plain sentence, no jargon>\n"
        "THESIS: <2-4 sentence plain-language summary, takeaway first>\n"
        "SENTIMENT_TAKEAWAY: <plain-language takeaway first, then evidence>\n"
        "FINANCIAL_TAKEAWAY: <plain-language takeaway first, then evidence>\n"
        "MACRO_TAKEAWAY: <plain-language takeaway first, then evidence>"
    )
    text = _llm_text(llm.invoke(prompt))

    fields = {"HEADLINE": "", "THESIS": "", "SENTIMENT_TAKEAWAY": "", "FINANCIAL_TAKEAWAY": "", "MACRO_TAKEAWAY": ""}
    current_key = None
    for line in text.splitlines():
        matched = False
        for key in fields:
            if line.upper().startswith(f"{key}:"):
                fields[key] = line.split(":", 1)[1].strip()
                current_key = key
                matched = True
                break
        if not matched and current_key:
            fields[current_key] += " " + line.strip()

    return {
        "headline_finding": fields["HEADLINE"].strip(),
        "thesis_summary": fields["THESIS"].strip(),
        "evidence_by_category": {
            "sentiment": fields["SENTIMENT_TAKEAWAY"].strip(),
            "financial": fields["FINANCIAL_TAKEAWAY"].strip(),
            "macro": fields["MACRO_TAKEAWAY"].strip(),
        },
    }


def build_memo_node(state: dict) -> dict:
    company_name = state.get("company_name")
    ticker = state.get("ticker")
    llm = get_llm()
    context = _specialist_context(state)

    step1 = _step1_evidence_pattern(company_name, context, llm)
    step2 = _step2_risk_factors(company_name, context, llm)
    step3 = _step3_invalidation_triggers(company_name, context, step1, step2, llm)
    step4 = _step4_catalysts_timeline(company_name, context, llm)

    reasoning_chain = [
        {"step": "identify_evidence_pattern", "output": step1},
        {"step": "identify_risk_factors", "output": step2},
        {"step": "identify_invalidation_triggers", "output": step3},
        {"step": "identify_catalysts_timeline", "output": step4},
    ]

    memo_fields = _synthesize_memo(company_name, ticker, context, reasoning_chain, llm)

    # Data-gap disclosure is enforced deterministically, not left to the LLM
    # to remember -- non-negotiable principle #5: failures always disclosed.
    data_gaps = []
    if state.get("sentiment_failed"):
        data_gaps.append("sentiment")
    if state.get("financial_failed"):
        data_gaps.append("financial")
    if state.get("macro_failed"):
        data_gaps.append("macro")

    if data_gaps:
        missing = ", ".join(data_gaps)
        available = ", ".join(k for k in ("sentiment", "financial", "macro") if k not in data_gaps)
        warning = f"⚠️ {missing.capitalize()} data was unavailable -- this memo reflects {available} research only."
        memo_fields["thesis_summary"] = f"{warning} {memo_fields['thesis_summary']}"

    return {
        "headline_finding": memo_fields["headline_finding"],
        "thesis_summary": memo_fields["thesis_summary"],
        "evidence_by_category": memo_fields["evidence_by_category"],
        "reasoning_chain": reasoning_chain,
        "risk_factors": _parse_bullets(step2),
        "invalidation_triggers": _parse_bullets(step3),
        "evidence_pattern_classification": step1,
        "data_gaps": data_gaps,
        "status": "review",
    }


# ---------------------------------------------------------------------------
# Checkpoint #2: memo review + open-ended Q&A (A2A-routed) + free-form takeaway
# ---------------------------------------------------------------------------

def checkpoint_2_review_node(state: dict) -> dict:
    """
    Loops on interrupt() within a single node execution -- the standard
    LangGraph pattern for a multi-turn HITL exchange -- rather than a
    graph-level self-loop edge (which caused concurrent writes to the same
    state key across parallel-looking supersteps). Each resume replays this
    function from the top; already-answered interrupt() calls replay from
    cache, so qa_history rebuilds deterministically and only the newest
    interrupt() call actually pauses.
    """
    memo = {
        "headline_finding": state.get("headline_finding"),
        "thesis_summary": state.get("thesis_summary"),
        "evidence_by_category": state.get("evidence_by_category"),
        "reasoning_chain": state.get("reasoning_chain"),
        "risk_factors": state.get("risk_factors"),
        "invalidation_triggers": state.get("invalidation_triggers"),
        "evidence_pattern_classification": state.get("evidence_pattern_classification"),
        "data_gaps": state.get("data_gaps"),
    }
    qa_history = state.get("checkpoint_2_qa_history") or []

    while True:
        user_input = interrupt({
            "type": "checkpoint_2_memo_review",
            "memo": memo,
            "qa_history": qa_history,
            "prompt": (
                "Review the memo above. Ask a follow-up question about any section, or share "
                "your own takeaway to close the session -- there's no approve/reject here, just "
                "your own conclusion."
            ),
        })

        action = (user_input or {}).get("action") if isinstance(user_input, dict) else None

        if action == "question":
            question = (user_input or {}).get("question", "")
            agent_id = route_question(question, llm=get_llm())
            message = send_message(agent_id, question, state)
            qa_history = qa_history + [{
                "question": question,
                "routed_to_agent": agent_id,
                "answer": message.answer,
            }]
            continue

        # Anything else (explicit "close", or no action) ends the session on
        # the user's own free-form takeaway -- no forced approve/reject, no
        # system verdict.
        takeaway = (user_input or {}).get("takeaway", "") if isinstance(user_input, dict) else ""
        return {"checkpoint_2_qa_history": qa_history, "user_takeaway": takeaway, "status": "complete"}
