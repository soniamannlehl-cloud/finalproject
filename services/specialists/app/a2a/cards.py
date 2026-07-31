"""
AgentCard definitions and the capability registry.

Cards are built with the official `a2a-sdk` protobuf types so the JSON
served at `/.well-known/agent.json` is spec-conformant rather than a
lookalike. The registry below maps a capability string to the Python
callable that serves it -- adding a specialist means adding one entry here,
with no change to the control plane.
"""

from collections.abc import Callable

from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from google.protobuf.json_format import MessageToDict

from contracts import Capability

from ..agents import company_profile, company_validation, financial_analyst, news_analyst

# capability -> handler.
#
# HANDLER CONTRACT: (inputs, run_id, task_id) ->
#     (evidence: list[Evidence], confidence: float,
#      degraded_reason: str | None, claims: list[Claim])
#
# Handlers RAISE on provider failure; the A2A server converts that into a
# FAILED result. They return empty evidence only when the provider genuinely
# had nothing to report.
CAPABILITY_HANDLERS: dict[str, Callable] = {
    Capability.COMPANY_VALIDATE.value: company_validation.handle,
    Capability.COMPANY_PROFILE.value: company_profile.handle,
    Capability.FINANCIAL_STATEMENTS.value: financial_analyst.handle_statements,
    Capability.FINANCIAL_RATIOS.value: financial_analyst.handle_ratios,
    Capability.NEWS_SENTIMENT.value: news_analyst.handle,
}

# agent_id -> the capabilities that agent serves.
AGENT_CAPABILITIES: dict[str, list[str]] = {
    company_validation.AGENT_ID: [Capability.COMPANY_VALIDATE.value],
    company_profile.AGENT_ID: [Capability.COMPANY_PROFILE.value],
    financial_analyst.AGENT_ID: [
        Capability.FINANCIAL_STATEMENTS.value,
        Capability.FINANCIAL_RATIOS.value,
    ],
    news_analyst.AGENT_ID: [Capability.NEWS_SENTIMENT.value],
}

_SKILL_SPECS: dict[str, dict] = {
    Capability.COMPANY_VALIDATE.value: {
        "name": "Company Validation",
        "description": (
            "Resolve a company name or stock ticker to candidate publicly traded "
            "companies. Distinguishes unlisted/private companies from unrecognized input."
        ),
        "tags": ["company", "validation", "ticker", "discovery"],
        "examples": ["NVDA", "Nvidia", "Apple Inc"],
    },
    Capability.COMPANY_PROFILE.value: {
        "name": "Company Profile",
        "description": (
            "Business description, sector, industry, scale, and listing details "
            "for a confirmed ticker."
        ),
        "tags": ["company", "profile", "classification"],
        "examples": ["NVDA"],
    },
    Capability.FINANCIAL_STATEMENTS.value: {
        "name": "Financial Statements",
        "description": (
            "Normalized income statement, balance sheet, and cash flow figures "
            "from reported filings."
        ),
        "tags": ["financials", "statements", "fundamentals"],
        "examples": ["NVDA"],
    },
    Capability.FINANCIAL_RATIOS.value: {
        "name": "Financial Ratios",
        "description": (
            "Deterministically computed valuation, profitability, growth, leverage, "
            "and cash-flow metrics, with a plain-language interpretation."
        ),
        "tags": ["financials", "ratios", "valuation", "metrics"],
        "examples": ["NVDA"],
    },
    Capability.NEWS_SENTIMENT.value: {
        "name": "News & Sentiment",
        "description": (
            "Recent news coverage and sentiment assessment, with explicit "
            "low-coverage flagging."
        ),
        "tags": ["news", "sentiment", "media"],
        "examples": ["NVDA"],
    },
}

_AGENT_DESCRIPTIONS: dict[str, str] = {
    company_validation.AGENT_ID: (
        "Validates that user input names a publicly traded company before any "
        "research is planned."
    ),
    company_profile.AGENT_ID: (
        "Establishes what the business is: sector, industry, scale, and description."
    ),
    financial_analyst.AGENT_ID: (
        "Retrieves reported financials and computes metrics deterministically in "
        "Python; an LLM interprets the results but never produces the numbers."
    ),
    news_analyst.AGENT_ID: (
        "Gathers recent coverage and assesses sentiment, flagging thin coverage "
        "rather than overstating confidence."
    ),
}


def build_agent_card(agent_id: str, base_url: str) -> AgentCard:
    """Construct the A2A AgentCard this agent publishes for discovery."""
    skills = [
        AgentSkill(
            id=cap,
            name=_SKILL_SPECS[cap]["name"],
            description=_SKILL_SPECS[cap]["description"],
            tags=_SKILL_SPECS[cap]["tags"],
            examples=_SKILL_SPECS[cap].get("examples", []),
            input_modes=["application/json"],
            output_modes=["application/json"],
        )
        for cap in AGENT_CAPABILITIES[agent_id]
    ]

    return AgentCard(
        name=agent_id,
        description=_AGENT_DESCRIPTIONS[agent_id],
        version="0.1.0",
        supported_interfaces=[
            AgentInterface(url=f"{base_url}/a2a", protocol_binding="HTTP_JSON")
        ],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        skills=skills,
    )


def card_to_dict(card: AgentCard) -> dict:
    """Serialize a protobuf AgentCard to JSON-safe dict for HTTP responses."""
    return MessageToDict(card, preserving_proto_field_name=True)


def all_agent_cards(base_url: str) -> list[dict]:
    """Every card this service publishes -- the Director's discovery payload."""
    return [card_to_dict(build_agent_card(aid, base_url)) for aid in AGENT_CAPABILITIES]


def resolve_handler(capability: str) -> Callable | None:
    return CAPABILITY_HANDLERS.get(capability)


def served_capabilities() -> list[str]:
    return sorted(CAPABILITY_HANDLERS)
