"""
The evidence brief the committee deliberates over.

This is the single largest lever on total run cost. Three frontier-model
agents debating raw filings, full article text, and complete metric dumps
would dominate spend and add nothing: the Bull Analyst does not need the
JSON shape of a cash flow statement to argue a case, it needs the numbers
that matter.

So the brief is a CONDENSED, human-readable digest, capped in size. It also
functions as a guardrail -- the committee can only argue from what the brief
contains, so it cannot cite evidence that was never gathered.
"""

from pydantic import BaseModel, Field


class BriefClaim(BaseModel):
    """One interpretive claim, with its citation preserved for traceability."""

    claim_id: str
    text: str
    category: str
    polarity: str
    confidence: float
    evidence_ids: list[str] = Field(default_factory=list)


class EvidenceBrief(BaseModel):
    """Everything the committee is permitted to reason from."""

    run_id: str
    ticker: str
    company_name: str
    industry: str | None = None
    classification: str | None = None

    thesis_statement: str | None = None
    thesis_stance: str | None = None
    thesis_confidence: float | None = None

    key_metrics: dict = Field(default_factory=dict)
    valuation: dict | None = None
    peer_positioning: dict = Field(default_factory=dict)
    detected_risks: list[dict] = Field(default_factory=list)
    sentiment: dict | None = None
    earnings_record: dict | None = None
    filings: dict | None = None

    claims: list[BriefClaim] = Field(default_factory=list)

    # Safety context. The committee is told what could NOT be verified so it
    # can temper its conviction rather than arguing confidently from
    # unvalidated material.
    evidence_score: float = 0.0
    coverage_ratio: float = 0.0
    declared_gaps: list[str] = Field(default_factory=list)
    unverified_checks: list[str] = Field(default_factory=list)

    def render(self) -> str:
        """Format the brief as the text the agents actually receive."""
        lines = [
            f"COMPANY: {self.company_name} ({self.ticker})",
            f"INDUSTRY: {self.industry or 'unknown'} "
            f"[{self.classification or 'generic'} framework]",
            "",
            "CURRENT THESIS:",
            f"  stance: {self.thesis_stance or 'none'} "
            f"(confidence {self.thesis_confidence if self.thesis_confidence is not None else 'n/a'})",
            f"  {self.thesis_statement or 'no thesis formed'}",
            "",
        ]

        if self.key_metrics:
            lines.append("KEY FINANCIAL METRICS:")
            for name, formatted in self.key_metrics.items():
                lines.append(f"  {name}: {formatted}")
            lines.append("")

        if self.valuation:
            lines.append("VALUATION (peer-relative):")
            for method in self.valuation.get("methods", []):
                lines.append(f"  {method}")
            if rng := self.valuation.get("range"):
                lines.append(f"  implied range: {rng}")
            lines.append("")

        if self.peer_positioning:
            lines.append("PEER POSITIONING:")
            for metric, detail in self.peer_positioning.items():
                lines.append(f"  {metric}: {detail}")
            lines.append("")

        if self.detected_risks:
            lines.append("DETECTED RISKS (from measured financial data):")
            for risk in self.detected_risks:
                lines.append(f"  [{risk.get('severity')}] {risk.get('title')}: {risk.get('detail')}")
            lines.append("")

        if self.sentiment:
            lines.append(
                f"NEWS SENTIMENT: {self.sentiment.get('tone')} across "
                f"{self.sentiment.get('article_count')} article(s)"
                + (" -- LOW COVERAGE, low confidence"
                   if self.sentiment.get("low_coverage") else "")
            )
            lines.append("")

        if self.earnings_record:
            lines.append(
                f"EARNINGS RECORD: {self.earnings_record.get('beats')} beat(s), "
                f"{self.earnings_record.get('misses')} miss(es); "
                f"{self.earnings_record.get('consecutive_misses')} consecutive miss(es)"
            )
            lines.append("")

        if self.filings:
            lines.append(
                f"SEC FILINGS: {self.filings.get('filing_count')} material filing(s); "
                f"annual report {'present' if self.filings.get('has_annual_report') else 'absent'}"
            )
            lines.append("")

        if self.claims:
            lines.append("ANALYST CLAIMS (cite these IDs when you use them):")
            for claim in self.claims:
                lines.append(f"  [{claim.claim_id}] ({claim.polarity}) {claim.text[:300]}")
            lines.append("")

        lines.extend([
            "EVIDENCE QUALITY:",
            f"  evidence score: {self.evidence_score:.2f}",
            f"  research coverage: {self.coverage_ratio:.0%}",
        ])
        if self.declared_gaps:
            lines.append(f"  DECLARED GAPS: {', '.join(self.declared_gaps)}")
        if self.unverified_checks:
            lines.append(f"  NOT VERIFIED: {'; '.join(self.unverified_checks)}")

        return "\n".join(lines)
