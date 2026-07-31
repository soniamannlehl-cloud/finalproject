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

from ..agents import company_validation

# capability -> handler. Handlers return (evidence, confidence, degraded_reason).
CAPABILITY_HANDLERS: dict[str, Callable] = {
    Capability.COMPANY_VALIDATE.value: company_validation.handle,
}

# agent_id -> the capabilities that agent serves.
AGENT_CAPABILITIES: dict[str, list[str]] = {
    company_validation.AGENT_ID: [Capability.COMPANY_VALIDATE.value],
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
}

_AGENT_DESCRIPTIONS: dict[str, str] = {
    company_validation.AGENT_ID: (
        "Validates that user input names a publicly traded company before any "
        "research is planned."
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
