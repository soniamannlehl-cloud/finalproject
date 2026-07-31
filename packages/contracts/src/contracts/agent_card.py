"""
A2A AgentCard -- how specialists advertise what they can do.

Each specialist publishes its card at `/.well-known/agent.json` (the A2A
convention). The Research Director fetches cards at startup, builds a
capability -> endpoint index, and routes tasks by capability match. No
component holds a hardcoded list of which agent does what.
"""

from pydantic import BaseModel, Field


class AgentSkill(BaseModel):
    """One capability an agent offers, with its I/O contract."""

    skill_id: str
    name: str
    description: str
    capability: str = Field(description="Matching key, e.g. 'financials.ratios'")
    input_schema: dict = Field(default_factory=dict, description="JSON Schema")
    output_schema: dict = Field(default_factory=dict, description="JSON Schema")
    typical_latency_ms: int | None = None


class AgentCard(BaseModel):
    """
    An agent's public description. Served over HTTP, consumed by the Director.

    Deliberately transport-explicit (`endpoint`): specialists live in a
    different container with an incompatible dependency tree, so they are
    genuinely only reachable over the network. A2A is the integration seam
    here, not decoration over an in-process function call.
    """

    agent_id: str
    name: str
    description: str
    version: str = "0.1.0"
    endpoint: str = Field(description="Base URL for A2A task submission")
    skills: list[AgentSkill] = Field(min_length=1)
    auth_scheme: str | None = None

    @property
    def capabilities(self) -> set[str]:
        """Flattened capability set, used for Director routing."""
        return {s.capability for s in self.skills}

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities


class AgentRegistry(BaseModel):
    """
    The Director's resolved view of the fleet.

    Built by fetching every configured specialist's card at startup and
    refreshed on discovery failures.
    """

    cards: list[AgentCard] = Field(default_factory=list)

    def resolve(self, capability: str) -> AgentCard | None:
        """First agent advertising this capability, or None if unserviceable."""
        for card in self.cards:
            if card.supports(capability):
                return card
        return None

    def missing(self, capabilities: set[str]) -> set[str]:
        """
        Capabilities no agent can serve.

        The Director calls this before dispatch so an unserviceable plan
        becomes a declared gap in the report rather than a runtime failure.
        """
        available: set[str] = set()
        for card in self.cards:
            available |= card.capabilities
        return capabilities - available
