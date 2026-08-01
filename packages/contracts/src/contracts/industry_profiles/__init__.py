"""Industry-specific research profiles — data-driven, extensible configuration."""

from .profile import IndustryProfile, RiskRuleSpec
from .profiles import PROFILES
from .registry import classify, get_profile, list_profiles

__all__ = [
    "IndustryProfile",
    "RiskRuleSpec",
    "PROFILES",
    "classify",
    "get_profile",
    "list_profiles",
]
