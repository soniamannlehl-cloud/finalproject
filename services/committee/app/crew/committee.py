"""
The CrewAI investment committee.

Three role-played agents deliberate: a Bull who must argue the case for
owning the company, a Bear who must argue against, and a CIO who weighs both
and renders a recommendation.

WHY CREWAI FOR THIS AND NOTHING ELSE: adversarial role-play with distinct
personas and sequential context handoff is precisely what CrewAI is built
for, and precisely what a LangGraph state machine would express clumsily.
The committee is also bounded and stateless -- no human checkpoints, no
persistence, one pass -- so none of LangGraph's strengths (interrupts,
checkpointing, conditional routing) are needed inside it.

THE ADVERSARIAL STRUCTURE IS A GUARDRAIL, not theatre. A single agent asked
to "analyze this company" tends toward whichever narrative the data most
readily suggests. Forcing a dedicated Bear to construct the strongest
opposing case surfaces the objections a one-sided analysis would omit --
and the CIO must then engage with them explicitly.
"""

import json
import logging
import re

from crewai import Agent, Crew, Process, Task

from ..config import get_settings
from .brief import EvidenceBrief

log = logging.getLogger(__name__)


def _llm_for(role: str) -> str:
    """CrewAI resolves model strings through litellm."""
    settings = get_settings()
    return {
        "bull": settings.model_bull,
        "bear": settings.model_bear,
        "cio": settings.model_cio,
    }.get(role, settings.model_cio)


def build_agents() -> dict[str, Agent]:
    """
    The three committee members.

    Backstories are written to make each agent's incentive explicit. The Bear
    is told that unchallenged optimism is how committees lose money -- an
    agent that hedges into neutrality provides no adversarial value.
    """
    bull = Agent(
        role="Bull Analyst",
        goal=(
            "Construct the strongest evidence-based case FOR investing in this company, "
            "citing only the evidence in the brief."
        ),
        backstory=(
            "You are a growth-oriented analyst known for identifying value others miss. "
            "Your job in committee is advocacy: build the most compelling case the "
            "evidence genuinely supports. You never invent figures, and you acknowledge "
            "the strongest counterarguments rather than pretending they do not exist -- "
            "a case that ignores obvious objections is dismissed by the CIO."
        ),
        llm=_llm_for("bull"),
        verbose=False,
        allow_delegation=False,
        max_iter=2,
    )

    bear = Agent(
        role="Bear Analyst",
        goal=(
            "Construct the strongest evidence-based case AGAINST investing in this "
            "company, citing only the evidence in the brief."
        ),
        backstory=(
            "You are a risk-focused analyst whose value to the committee is finding "
            "what everyone else overlooked. Unchallenged optimism is how investment "
            "committees lose money. Your job is to surface every genuine weakness the "
            "evidence supports -- concentration, leverage, valuation, deteriorating "
            "fundamentals, thin data. You never invent figures, and you do not "
            "manufacture concerns the evidence does not support."
        ),
        llm=_llm_for("bear"),
        verbose=False,
        allow_delegation=False,
        max_iter=2,
    )

    cio = Agent(
        role="Chief Investment Officer",
        goal=(
            "Weigh the bull and bear cases against the evidence and render a "
            "recommendation with an explicit, defensible rationale."
        ),
        backstory=(
            "You chair the investment committee. You have seen confident analyses "
            "built on thin data and you are unimpressed by conviction unsupported by "
            "evidence. You engage with the bear case explicitly rather than dismissing "
            "it, you say plainly when evidence is insufficient to justify a directional "
            "view, and you state what would change your mind."
        ),
        llm=_llm_for("cio"),
        verbose=False,
        allow_delegation=False,
        max_iter=2,
    )

    return {"bull": bull, "bear": bear, "cio": cio}


def build_tasks(agents: dict[str, Agent], brief_text: str) -> list[Task]:
    """
    Sequential debate: Bull, then Bear (seeing the bull case), then CIO.

    The Bear receives the Bull's argument as context, so it rebuts a specific
    case rather than arguing into a vacuum. That handoff is what makes this a
    debate rather than two independent monologues.
    """
    bull_task = Task(
        description=(
            f"Review this investment research brief and argue the case FOR investing.\n\n"
            f"{brief_text}\n\n"
            "Write 4-6 sentences. Cite specific figures from the brief. Reference claim "
            "IDs in [brackets] where you rely on them. Do not introduce facts that are "
            "not in the brief. End with your conviction as a number from 0.0 to 1.0 on "
            "its own line, formatted exactly as: CONVICTION: 0.XX"
        ),
        expected_output="A bull case of 4-6 sentences citing brief figures, ending with CONVICTION: 0.XX",
        agent=agents["bull"],
    )

    bear_task = Task(
        description=(
            "Review the same brief and the bull case just presented. Argue the case "
            "AGAINST investing.\n\n"
            f"{brief_text}\n\n"
            "Write 4-6 sentences. Address the bull case's weakest points directly. Cite "
            "specific figures from the brief and reference claim IDs in [brackets]. Do "
            "not invent concerns the evidence does not support. End with your conviction "
            "as a number from 0.0 to 1.0 on its own line, formatted exactly as: "
            "CONVICTION: 0.XX"
        ),
        expected_output="A bear case of 4-6 sentences rebutting the bull case, ending with CONVICTION: 0.XX",
        agent=agents["bear"],
        context=[bull_task],
    )

    cio_task = Task(
        description=(
            "You have heard the bull and bear cases. Render the committee's "
            "recommendation.\n\n"
            f"{brief_text}\n\n"
            "Consider evidence quality explicitly: an evidence score below 0.60, or "
            "materially incomplete coverage, means the committee should NOT issue a "
            "directional view regardless of how appealing either case sounds.\n\n"
            "Respond with ONLY a JSON object:\n"
            "{\n"
            '  "action": "buy" | "hold" | "sell" | "insufficient_evidence",\n'
            '  "confidence": 0.0-1.0,\n'
            '  "rationale": "3-5 sentences engaging with BOTH cases",\n'
            '  "dissent": "the strongest surviving counterargument, or null",\n'
            '  "conditions_that_would_change_this": ["observable trigger", "..."],\n'
            '  "time_horizon": "e.g. 12 months"\n'
            "}"
        ),
        expected_output="A single JSON object with action, confidence, rationale, dissent, conditions, time_horizon",
        agent=agents["cio"],
        context=[bull_task, bear_task],
    )

    return [bull_task, bear_task, cio_task]


def _extract_conviction(text: str) -> float:
    """Parse the CONVICTION line, defaulting mid-scale when absent."""
    match = re.search(r"CONVICTION:\s*([01]?\.\d+|[01])", text or "", re.IGNORECASE)
    if not match:
        return 0.5
    try:
        return max(0.0, min(1.0, float(match.group(1))))
    except ValueError:
        return 0.5


def _extract_claim_ids(text: str) -> list[str]:
    """Claim IDs the agent cited in [brackets] -- preserves traceability."""
    return sorted(set(re.findall(r"\[(claim_[A-Za-z0-9_]+)\]", text or "")))


def _parse_cio_json(text: str) -> dict:
    """
    Extract the CIO's JSON verdict.

    Models wrap JSON in prose or code fences despite instructions, so the
    first balanced object is extracted rather than assuming a clean payload.
    Falling back to INSUFFICIENT_EVIDENCE on a parse failure is deliberate:
    an unparseable verdict must not become an accidental BUY.
    """
    if not text:
        return {}

    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None

    if candidate is None:
        start = text.find("{")
        if start >= 0:
            depth = 0
            for i, ch in enumerate(text[start:], start):
                depth += (ch == "{") - (ch == "}")
                if depth == 0:
                    candidate = text[start:i + 1]
                    break

    if candidate is None:
        return {}

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        log.warning("CIO verdict was not parseable JSON")
        return {}


def run_committee(brief: EvidenceBrief) -> dict:
    """
    Convene the committee and return its proposed recommendation.

    Note this returns a PROPOSAL. The API service then applies the
    deterministic policy gate, which can downgrade or suppress it entirely --
    the committee argues, the policy decides what may actually be said.
    """
    settings = get_settings()
    brief_text = brief.render()

    agents = build_agents()
    tasks = build_tasks(agents, brief_text)

    crew = Crew(
        agents=[agents["bull"], agents["bear"], agents["cio"]],
        tasks=tasks,
        process=Process.sequential,
        verbose=False,
        # Memory off: each run is an independent deliberation, and cross-run
        # memory would let one company's conclusions leak into another's.
        memory=False,
    )

    log.info("convening committee for %s (%d claims in brief)", brief.ticker, len(brief.claims))
    crew.kickoff()

    bull_text = str(tasks[0].output) if tasks[0].output else ""
    bear_text = str(tasks[1].output) if tasks[1].output else ""
    cio_text = str(tasks[2].output) if tasks[2].output else ""

    verdict = _parse_cio_json(cio_text)

    action = str(verdict.get("action", "insufficient_evidence")).lower().strip()
    if action not in ("buy", "hold", "sell", "insufficient_evidence"):
        log.warning("CIO returned unrecognized action %r; defaulting to insufficient_evidence", action)
        action = "insufficient_evidence"

    try:
        confidence = max(0.0, min(1.0, float(verdict.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    return {
        "action": action,
        "confidence": confidence,
        "cio_rationale": verdict.get("rationale") or cio_text[:1000] or "no rationale produced",
        "dissent": verdict.get("dissent"),
        "conditions_that_would_change_this": verdict.get("conditions_that_would_change_this") or [],
        "time_horizon": verdict.get("time_horizon"),
        "bull_case": {
            "role": "bull_analyst",
            "argument": bull_text,
            "conviction": _extract_conviction(bull_text),
            "claim_ids": _extract_claim_ids(bull_text),
        },
        "bear_case": {
            "role": "bear_analyst",
            "argument": bear_text,
            "conviction": _extract_conviction(bear_text),
            "claim_ids": _extract_claim_ids(bear_text),
        },
        "models_used": {
            "bull": settings.model_bull,
            "bear": settings.model_bear,
            "cio": settings.model_cio,
        },
    }
