"""
tools/a2a_router.py

Lightweight in-process implementation of the A2A (Agent2Agent) protocol's
core concepts -- agent cards that advertise what an agent owns, and
capability-based message routing -- used to satisfy the brief's requirement
that Checkpoint #2 Q&A follow-ups route to the SPECIFIC specialist agent
that owns that topic, never answered generically by the Orchestrator.

A real A2A deployment exposes each agent as an HTTP service with a published
AgentCard at a well-known URL. Here all 3 specialists run in the same
LangGraph process, so we keep the same conceptual pieces (AgentCard,
A2AMessage, capability-based routing) but dispatch in-process via a handler
registry instead of network calls.

Wiring convention: graph.py registers each specialist's `answer_question`
function against its agent_id via register_handler() once, at graph-build
time (explicit wiring, not an import-time side effect).
"""

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass
class AgentCard:
    """Mirrors A2A's AgentCard: identity, description, and owned topics."""
    agent_id: str
    name: str
    description: str
    topics: list


@dataclass
class A2AMessage:
    """A routed request/response envelope, mirroring an A2A Task/Message."""
    from_agent: str
    to_agent: str
    question: str
    answer: Optional[str] = None


AGENT_CARDS = [
    AgentCard(
        agent_id="sentiment_analyst",
        name="Sentiment Analyst",
        description=(
            "Owns news coverage, media sentiment, public perception, sentiment "
            "trend, and article-level questions."
        ),
        topics=["sentiment", "news", "media", "coverage", "perception", "article", "press", "headline"],
    ),
    AgentCard(
        agent_id="financial_analyst",
        name="Financial Analyst",
        description=(
            "Owns financial ratios, earnings, balance sheet, revenue, margins, "
            "valuation multiples, debt, and cash flow questions."
        ),
        topics=["financial", "ratio", "earning", "revenue", "margin", "valuation",
                "p/e", "eps", "debt", "cash flow", "balance sheet", "profit"],
    ),
    AgentCard(
        agent_id="macro_industry_analyst",
        name="Macro & Industry Analyst",
        description=(
            "Owns macroeconomic conditions, interest rates, sector performance, "
            "competitive landscape, and industry trend questions."
        ),
        topics=["macro", "economy", "interest rate", "sector", "industry",
                "competitor", "regulation", "inflation", "gdp", "unemployment"],
    ),
]

_HANDLERS: dict = {}


def register_handler(agent_id: str, handler: Callable) -> None:
    """Publish the function A2A messages for this agent_id get dispatched to.
    Called once per specialist at graph-build time, e.g.:
        register_handler("sentiment_analyst", sentiment_analyst.answer_question)
    """
    _HANDLERS[agent_id] = handler


def route_question(question: str, llm=None) -> str:
    """
    Decide which specialist agent owns this question. Tries deterministic
    keyword matching against each AgentCard's topics first (fast, free,
    inspectable in traces); falls back to an LLM classification call only
    when no keyword match is found, since natural-language phrasing won't
    always contain an obvious keyword.

    Returns an agent_id from AGENT_CARDS, or "unrouted" if nothing matches
    and no llm was supplied to break the tie.
    """
    lowered = question.lower()
    for card in AGENT_CARDS:
        if any(topic in lowered for topic in card.topics):
            return card.agent_id

    if llm is None:
        return "unrouted"

    card_list = "\n".join(f"- {c.agent_id}: {c.description}" for c in AGENT_CARDS)
    prompt = (
        "A user asked a follow-up question about an investment research memo. "
        "Decide which specialist agent owns this topic. Respond with ONLY the "
        "agent_id, nothing else.\n\n"
        f"Specialists:\n{card_list}\n\n"
        f"Question: {question}\n\nagent_id:"
    )
    response = llm.invoke(prompt)
    text = (response.content if hasattr(response, "content") else str(response)).strip().lower()
    for card in AGENT_CARDS:
        if card.agent_id in text:
            return card.agent_id
    return "unrouted"


def send_message(to_agent: str, question: str, state: dict) -> A2AMessage:
    """
    Dispatch a Q&A question to the owning specialist's registered handler
    and return the completed A2AMessage (with .answer populated).
    """
    message = A2AMessage(from_agent="orchestrator", to_agent=to_agent, question=question)
    handler = _HANDLERS.get(to_agent)
    if handler is None:
        message.answer = (
            "I couldn't route this question to a specialist -- no handler is "
            "registered for that topic yet."
        )
        return message
    message.answer = handler(question, state)
    return message
