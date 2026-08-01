"""
Industry profile registry — classification and lookup.

The Planner calls `classify()` then `get_profile()` before building tasks.
All downstream agents receive the selected profile via task inputs.
"""

from ..enums import IndustryPlaybook
from .profile import IndustryProfile
from .profiles import PROFILES


def classify(sector: str | None, industry: str | None) -> tuple[IndustryPlaybook, str]:
    """
    Deterministically select a profile from yfinance classification strings.

    Industry is checked before sector because it is more specific.
    """
    industry_l = (industry or "").lower()
    sector_l = (sector or "").lower()

    # REIT subclasses often include "Retail" in the name — check REIT first.
    if "reit" in industry_l:
        return IndustryPlaybook.REIT, f"industry '{industry}' matched 'reit'"

    # Profiles where industry names overlap (e.g. retail vs REIT) are checked
    # in a stable priority order rather than dict iteration order.
    priority = [
        IndustryPlaybook.INSURANCE,
        IndustryPlaybook.BANKING,
        IndustryPlaybook.TECHNOLOGY,
        IndustryPlaybook.HEALTHCARE,
        IndustryPlaybook.ENERGY,
        IndustryPlaybook.TELECOMMUNICATIONS,
        IndustryPlaybook.CONSUMER_STAPLES,
        IndustryPlaybook.RETAIL,
        IndustryPlaybook.MANUFACTURING,
        IndustryPlaybook.INDUSTRIALS,
        IndustryPlaybook.UTILITIES,
        IndustryPlaybook.REIT,
    ]

    for profile_id in priority:
        profile = PROFILES[profile_id]
        for token in profile.industry_matches:
            if token in industry_l:
                return profile.profile_id, f"industry '{industry}' matched '{token}'"

    for profile_id in priority:
        profile = PROFILES[profile_id]
        for token in profile.sector_matches:
            if token in sector_l:
                return profile.profile_id, f"sector '{sector}' matched '{token}'"

    return (
        IndustryPlaybook.GENERIC,
        f"no profile matched sector={sector!r} industry={industry!r}; using general framework",
    )


def get_profile(profile_id: IndustryPlaybook) -> IndustryProfile:
    return PROFILES.get(profile_id, PROFILES[IndustryPlaybook.GENERIC])


def list_profiles() -> list[IndustryProfile]:
    return list(PROFILES.values())
