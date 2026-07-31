"""
The final investment report -- the user-facing deliverable.

The same model renders twice: to HTML for in-app preview, and through
WeasyPrint to PDF for download. One template, two outputs, so what the
user sees on screen is exactly what they download.
"""

from datetime import datetime

from pydantic import BaseModel, Field

from .evidence import Evidence
from .recommendation import Recommendation
from .thesis import ThesisVersion


class ReportSection(BaseModel):
    """One rendered section. `claim_ids` back every factual assertion."""

    section_id: str
    title: str
    order: int
    body: str
    claim_ids: list[str] = Field(default_factory=list)
    chart_svg: str | None = Field(
        default=None, description="Inline SVG -- keeps the PDF path JS-free"
    )


class InvestmentReport(BaseModel):
    """
    Complete research note.

    `limitations` and `declared_gaps` are mandatory rather than optional:
    a report that silently omits what it could not determine would violate
    the platform's core transparency guarantee.
    """

    report_id: str
    run_id: str
    ticker: str
    company_name: str
    generated_at: datetime

    recommendation: Recommendation
    final_thesis: ThesisVersion
    sections: list[ReportSection] = Field(default_factory=list)

    sources: list[Evidence] = Field(
        default_factory=list, description="Resolved evidence backing the citations"
    )
    limitations: list[str] = Field(default_factory=list)
    declared_gaps: list[str] = Field(
        default_factory=list, description="Research that was planned but could not be completed"
    )

    approved_by_human: bool = False
    approved_at: datetime | None = None

    def ordered_sections(self) -> list[ReportSection]:
        return sorted(self.sections, key=lambda s: s.order)
