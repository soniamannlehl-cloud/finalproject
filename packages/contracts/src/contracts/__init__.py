"""
irp-contracts -- shared data contracts for the AI Investment Research Platform.

This package is the integration seam between three services that cannot
share a Python environment (LangGraph, A2A/tooling, and CrewAI have
mutually incompatible dependency trees). It depends on Pydantic and
nothing else; adding a framework dependency here would defeat the entire
3-service architecture.
"""

from .a2a import A2ATaskRequest, A2ATaskResult
from .agent_card import AgentCard, AgentRegistry, AgentSkill
from .enums import (
    Capability,
    Criticality,
    HumanDecision,
    IndustryPlaybook,
    Polarity,
    RecommendationAction,
    Severity,
    SourceType,
    TaskState,
    ValidationStatus,
    ValuationMethod,
)
from .evidence import FRESHNESS_POLICY, Claim, Evidence
from .plan import ResearchPlan, TaskSpec
from .policy import (
    MIN_CONFIDENCE_FOR_DIRECTIONAL,
    MIN_EVIDENCE_SCORE_FOR_ANY_CALL,
    GateResult,
    apply_recommendation_gate,
    compute_evidence_score,
)
from .recommendation import CommitteePosition, Recommendation
from .report import InvestmentReport, ReportSection
from .safety import CoverageReport, SafetyFinding, SafetyReport
from .thesis import StructuredThesis, ThesisHistory, ThesisVersion
from .industry_profiles import IndustryProfile, PROFILES, RiskRuleSpec, classify, get_profile, list_profiles

__version__ = "0.1.0"

__all__ = [
    # a2a
    "A2ATaskRequest",
    "A2ATaskResult",
    # agent cards
    "AgentCard",
    "AgentRegistry",
    "AgentSkill",
    # enums
    "Capability",
    "Criticality",
    "HumanDecision",
    "IndustryPlaybook",
    "Polarity",
    "RecommendationAction",
    "Severity",
    "SourceType",
    "TaskState",
    "ValidationStatus",
    "ValuationMethod",
    # evidence
    "Claim",
    "Evidence",
    "FRESHNESS_POLICY",
    # plan
    "ResearchPlan",
    "TaskSpec",
    # policy
    "GateResult",
    "apply_recommendation_gate",
    "compute_evidence_score",
    "MIN_CONFIDENCE_FOR_DIRECTIONAL",
    "MIN_EVIDENCE_SCORE_FOR_ANY_CALL",
    # recommendation
    "CommitteePosition",
    "Recommendation",
    # report
    "InvestmentReport",
    "ReportSection",
    # safety
    "CoverageReport",
    "SafetyFinding",
    "SafetyReport",
    # thesis
    "StructuredThesis",
    "ThesisHistory",
    "ThesisVersion",
    # industry profiles
    "IndustryProfile",
    "RiskRuleSpec",
    "PROFILES",
    "classify",
    "get_profile",
    "list_profiles",
]
