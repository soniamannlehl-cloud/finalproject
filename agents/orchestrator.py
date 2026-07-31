"""
agents/orchestrator.py

Orchestrator Agent -- synthesizes the 3 specialists' research into a
beginner-friendly memo plus a draft investment recommendation, with
explicit, inspectable planning/reasoning steps. Owns HITL Checkpoint #2:
an investment-committee approval gate where a human can ask follow-up
questions (routed via A2A to the owning specialist), then must approve,
reject, or request a revision before any recommendation is finalized. A
"revise" decision sends feedback back to this same Orchestrator, which
updates its thesis and recommendation to address it -- the system doesn't
just re-run from scratch, it replans in light of new committee input.

PRODUCT PRINCIPLE: the draft recommendation is a directional, analyst-style
thesis conclusion (e.g. "constructive", "cautious", "neutral" + rationale)
drafted FOR the investment committee's review -- never surfaced to an end
investor, and never finalized, until a human approves it at Checkpoint #2.
It is not personalized advice and is never based on a stored user profile
-- no persistent user profile exists anywhere in this system.
"""

from langgraph.types import interrupt

from config import get_llm, MAX_REVISION_ROUNDS
from tools.a2a_router import route_question, send_message

PERSONA = (
    "You are a senior research analyst who synthesizes specialist research "
    "into clear, evidence-based investment memos and drafts a recommendation "
    "for an investment committee's review and approval -- presenting "
    "patterns in the evidence, not issuing advice directly to an end investor."
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


def _revision_context(state: dict) -> str:
    """
    Built only when the committee sent this memo back for revision. Feeding
    the prior recommendation + committee feedback into every reasoning step
    is what makes this a genuine thesis UPDATE in light of new input, not a
    from-scratch re-run that happens to look similar.
    """
    if state.get("committee_decision") != "revise":
        return ""
    return (
        "\n\nTHIS IS A REVISION. The investment committee reviewed your prior recommendation "
        f'and sent it back with this feedback: "{state.get("committee_feedback")}"\n'
        f"Your prior recommendation was: {state.get('draft_recommendation')}\n"
        "Update your reasoning to directly address this feedback -- don't just restate the "
        "prior analysis."
    )


# ---------------------------------------------------------------------------
# Explicit planning / task decomposition -- 5 separate LLM calls so each
# sub-step is its own inspectable span in LangSmith traces, not one opaque
# call that hides the reasoning.
# ---------------------------------------------------------------------------

def _step1_evidence_pattern(company_name: str, context: str, revision_ctx: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 1 of 5 -- identify the evidence pattern.\n\n"
        f"Company: {company_name}\n\n{context}{revision_ctx}\n\n"
        "Classify the overall EVIDENCE PATTERN this research fits (e.g. \"fits a growth-style "
        "profile\", \"fits a value-style profile\", \"turnaround story\", \"mixed/inconclusive "
        "signals\"). This is a DESCRIPTIVE classification of the evidence only -- never "
        "personalized to any individual user (no user profile exists in this system). Respond "
        "in 1-2 sentences."
    )
    return _llm_text(llm.invoke(prompt))


def _step2_risk_factors(company_name: str, context: str, revision_ctx: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 2 of 5 -- identify risk factors.\n\n"
        f"Company: {company_name}\n\n{context}{revision_ctx}\n\n"
        "Identify the 2-3 MOST decision-relevant risk factors for THIS SPECIFIC company based on "
        "the research above -- not a generic template list. List each as a bullet point starting "
        "with '-', one sentence each, plain language."
    )
    return _llm_text(llm.invoke(prompt))


def _step3_invalidation_triggers(company_name: str, context: str, revision_ctx: str,
                                  step1: str, step2: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 3 of 5 -- identify invalidation triggers.\n\n"
        f"Company: {company_name}\n\n{context}{revision_ctx}\n\n"
        f"Evidence pattern identified in step 1: {step1}\n"
        f"Risk factors identified in step 2: {step2}\n\n"
        "Identify 2-3 specific, observable events or data points that would INVALIDATE the "
        "evidence pattern above -- things a beginner investor could actually watch for. List "
        "each as a bullet point starting with '-', one sentence each, plain language."
    )
    return _llm_text(llm.invoke(prompt))


def _step4_catalysts_timeline(company_name: str, context: str, revision_ctx: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 4 of 5 -- identify catalysts and timeline.\n\n"
        f"Company: {company_name}\n\n{context}{revision_ctx}\n\n"
        "Identify near-term catalysts (upcoming events, earnings dates, industry developments) "
        "that could move the evidence pattern in either direction, and a rough timeline for each. "
        "2-3 bullet points starting with '-', plain language."
    )
    return _llm_text(llm.invoke(prompt))


def _step5_draft_recommendation(company_name: str, context: str, revision_ctx: str,
                                 step1: str, step2: str, step3: str, step4: str, llm) -> str:
    prompt = (
        f"{PERSONA}\n\n"
        "STEP 5 of 5 -- draft a recommendation for the investment committee.\n\n"
        f"Company: {company_name}\n\n{context}{revision_ctx}\n\n"
        f"Evidence pattern: {step1}\n"
        f"Risk factors: {step2}\n"
        f"Invalidation triggers: {step3}\n"
        f"Catalysts/timeline: {step4}\n\n"
        "Draft a directional recommendation FOR THE COMMITTEE'S REVIEW -- this will NOT reach any "
        "end investor unless the committee approves it. State a clear professional characterization "
        "(e.g. \"Constructive\", \"Cautious\", \"Neutral\", \"Constructive with reservations\") and "
        "2-3 sentences of rationale tying directly to the evidence above. This is a draft for human "
        "approval, not unsupervised advice -- do not address the reader as an individual investor."
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
        "- This memo describes evidence; the separate recommendation (drafted in step 5) is what "
        "goes to the committee -- don't restate a verdict here.\n\n"
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
    revision_ctx = _revision_context(state)
    is_revision = state.get("committee_decision") == "revise"

    step1 = _step1_evidence_pattern(company_name, context, revision_ctx, llm)
    step2 = _step2_risk_factors(company_name, context, revision_ctx, llm)
    step3 = _step3_invalidation_triggers(company_name, context, revision_ctx, step1, step2, llm)
    step4 = _step4_catalysts_timeline(company_name, context, revision_ctx, llm)
    step5 = _step5_draft_recommendation(company_name, context, revision_ctx, step1, step2, step3, step4, llm)

    reasoning_chain = [
        {"step": "identify_evidence_pattern", "output": step1},
        {"step": "identify_risk_factors", "output": step2},
        {"step": "identify_invalidation_triggers", "output": step3},
        {"step": "identify_catalysts_timeline", "output": step4},
        {"step": "draft_recommendation", "output": step5},
    ]

    memo_fields = _synthesize_memo(company_name, ticker, context, reasoning_chain, llm)

    # Data-gap disclosure is enforced deterministically, not left to the LLM
    # to remember -- non-negotiable principle: failures always disclosed.
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

    revision_count = state.get("revision_count") or 0
    if is_revision:
        revision_count += 1

    return {
        "headline_finding": memo_fields["headline_finding"],
        "thesis_summary": memo_fields["thesis_summary"],
        "evidence_by_category": memo_fields["evidence_by_category"],
        "reasoning_chain": reasoning_chain,
        "risk_factors": _parse_bullets(step2),
        "invalidation_triggers": _parse_bullets(step3),
        "evidence_pattern_classification": step1,
        "data_gaps": data_gaps,
        "draft_recommendation": step5,
        "revision_count": revision_count,
        "status": "review",
    }


# ---------------------------------------------------------------------------
# Checkpoint #2: investment committee approval gate
# Q&A (A2A-routed) + approve / reject / revise -- a genuine decision point,
# not a rubber-stamp confirmation: "revise" sends feedback back to
# build_memo_node, which updates the thesis and recommendation to address it.
# ---------------------------------------------------------------------------

def checkpoint_2_review_node(state: dict) -> dict:
    """
    Loops on interrupt() within a single node execution -- the standard
    LangGraph pattern for a multi-turn HITL exchange -- rather than a
    graph-level self-loop edge (which caused concurrent writes to the same
    state key across parallel-looking supersteps, see graph.py). Each
    resume replays this function from the top; already-answered interrupt()
    calls replay from cache, so qa_history rebuilds deterministically and
    only the newest interrupt() call actually pauses.
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
        "draft_recommendation": state.get("draft_recommendation"),
        "revision_count": state.get("revision_count") or 0,
    }
    qa_history = state.get("checkpoint_2_qa_history") or []

    revision_count = state.get("revision_count") or 0
    if revision_count >= MAX_REVISION_ROUNDS:
        # Safety cap: don't let a revise/feedback cycle run forever.
        return {
            "checkpoint_2_qa_history": qa_history,
            "committee_decision": "rejected",
            "committee_feedback": (
                f"Automatically closed as rejected after reaching the maximum of "
                f"{MAX_REVISION_ROUNDS} revision rounds without approval."
            ),
            "status": "complete",
        }

    while True:
        user_input = interrupt({
            "type": "checkpoint_2_committee_approval",
            "memo": memo,
            "qa_history": qa_history,
            "prompt": (
                "Review the memo and draft recommendation above. Ask a follow-up question about "
                "any section, or render a decision: approve, reject, or request a revision with "
                "feedback -- nothing is finalized until you approve it."
            ),
        })

        if not isinstance(user_input, dict):
            continue  # malformed input -- ask again rather than guessing

        action = user_input.get("action")

        if action == "question":
            question = user_input.get("question", "")
            agent_id = route_question(question, llm=get_llm())
            message = send_message(agent_id, question, state)
            qa_history = qa_history + [{
                "question": question,
                "routed_to_agent": agent_id,
                "answer": message.answer,
            }]
            continue

        if action == "decision":
            decision = user_input.get("decision")
            feedback = user_input.get("feedback", "")

            if decision == "revise":
                if not feedback:
                    continue  # revision requires feedback to act on -- ask again
                return {
                    "checkpoint_2_qa_history": qa_history,
                    "committee_decision": "revise",
                    "committee_feedback": feedback,
                    "status": "review",
                }

            if decision in ("approved", "rejected", "approve", "reject"):
                normalized = "approved" if decision.startswith("approve") else "rejected"
                return {
                    "checkpoint_2_qa_history": qa_history,
                    "committee_decision": normalized,
                    "committee_feedback": feedback,
                    "user_takeaway": feedback,
                    "status": "complete",
                }

        # Unrecognized action/decision -- a genuine gate doesn't guess; ask again.
        continue
