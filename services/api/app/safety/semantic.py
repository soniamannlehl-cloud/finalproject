"""
Layer 2 -- semantic safety checks.

Only two checks genuinely require language understanding:

  HALLUCINATION   does this claim actually follow from the evidence it cites?
                  A claim can cite a real evidence ID and still assert
                  something that evidence does not support -- which the
                  deterministic citation check cannot detect.

  CONTRADICTION   do claims conflict with each other, or with facts as filed
                  with the SEC? Disagreement between a vendor figure and a
                  filed XBRL fact is a genuine finding, not noise.

CRITICAL DESIGN RULE: when these checks cannot run -- no LLM configured, no
claims to examine, the model unavailable -- they report NOT_CHECKED. They
never report "passed". A safety pipeline that silently returns green because
it had nothing to look at is worse than no pipeline, because it manufactures
false assurance. `checks_skipped` propagates into the evidence score so an
unverified run cannot present itself as a verified one.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from contracts import SafetyFinding, Severity

from ..config import get_settings

log = logging.getLogger(__name__)

MAX_CLAIMS_PER_CHECK = 25  # bounds cost and context size


@dataclass
class SemanticResult:
    """Outcome of the semantic layer, including whether it ran at all."""

    findings: list[SafetyFinding] = field(default_factory=list)
    unsupported_claim_ids: list[str] = field(default_factory=list)
    contradiction_count: int = 0
    checks_run: list[str] = field(default_factory=list)
    checks_skipped: list[dict] = field(default_factory=list)

    @property
    def was_verified(self) -> bool:
        """True only if both semantic checks actually executed."""
        return {"hallucination", "contradiction"}.issubset(set(self.checks_run))


def _finding(check: str, severity: Severity, message: str, claims=None) -> SafetyFinding:
    return SafetyFinding(
        finding_id=f"f_{uuid.uuid4().hex[:10]}",
        check_name=check,
        severity=severity,
        message=message,
        related_claim_ids=claims or [],
        related_evidence_ids=[],
        detected_at=datetime.now(timezone.utc),
    )


_HALLUCINATION_PROMPT = """You are a fact-checker verifying that analytical claims are supported by their cited evidence.

For each claim, decide whether it is SUPPORTED by the evidence shown.
A claim is UNSUPPORTED if it asserts facts, figures, or conclusions the evidence does not contain.
Interpretation and reasonable inference from the evidence ARE supported.
Do not judge whether the claim is correct in the real world -- only whether the evidence supports it.

{items}

Respond as JSON only:
{{"results": [{{"claim_id": "...", "supported": true|false, "reason": "..."}}]}}"""


_CONTRADICTION_PROMPT = """You are reviewing an investment research file for internal contradictions.

Claims made during research:
{claims}

{filed_facts}

Identify pairs of claims that genuinely CONTRADICT each other, or claims contradicted by the
filed facts. Differing emphasis, or a bull point coexisting with a bear point, is NOT a
contradiction -- balanced research contains both. Only flag logically incompatible statements.

Respond as JSON only:
{{"contradictions": [{{"claim_ids": ["...", "..."], "explanation": "..."}}]}}"""


def _llm_json(prompt: str, max_tokens: int = 900) -> dict | None:
    settings = get_settings()
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.resolve_model("safety_semantic"),
            temperature=0,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(response.choices[0].message.content or "{}")
    except Exception as e:  # noqa: BLE001
        log.warning("semantic check LLM call failed: %s", e)
        return None


def _render_evidence(ev: dict) -> str:
    """
    Render an evidence record with enough substance to check a claim against.

    Passing only `summary` here caused false positives: a claim citing
    specific margin figures was flagged unsupported because the summary said
    merely "16/16 metrics computable". The checker must see the actual
    values, or it penalises claims for the renderer's omissions rather than
    the claim's own faults.

    Content is rendered per-capability and truncated, because these payloads
    can be large and the whole set is sent in one prompt.
    """
    capability = ev.get("capability", "")
    content = ev.get("content") or {}
    lines: list[str] = []

    if capability == "financials.ratios":
        for name, m in (content.get("metrics") or {}).items():
            if m.get("meaningful"):
                lines.append(f"{name}={m['formatted']}")
            else:
                lines.append(f"{name}=not meaningful ({m.get('flag')})")

    elif capability == "financials.statements":
        for key in ("revenue", "net_income", "operating_income", "ebitda",
                    "total_debt", "total_equity", "operating_cash_flow"):
            if content.get(key) is not None:
                lines.append(f"{key}={content[key]}")

    elif capability == "news.sentiment":
        lines.append(f"article_count={content.get('article_count')}")
        lines.append(f"tone={content.get('tone')}")
        lines.append(f"low_coverage={content.get('low_coverage')}")
        for article in (content.get("articles") or [])[:8]:
            lines.append(f"headline: {article.get('title')}")

    elif capability == "competitors.analysis":
        lines.append(f"peers={[p['ticker'] for p in (content.get('peers') or [])]}")
        for metric, c in (content.get("comparison") or {}).items():
            if c.get("subject") is not None and c.get("peer_median") is not None:
                lines.append(
                    f"{metric}: subject={c['subject']:.4g} peer_median={c['peer_median']:.4g} "
                    f"percentile={c.get('percentile_rank')}"
                )

    elif capability == "valuation.estimate":
        for r in (content.get("results") or []):
            if r.get("applicable"):
                lines.append(
                    f"{r['label']}: peer_median={r['peer_median_multiple']}x "
                    f"implied_price={r.get('implied_price_per_share')}"
                )
            else:
                lines.append(f"{r['label']}: not applicable ({r.get('reason')})")
        if vr := content.get("valuation_range"):
            lines.append(f"range={vr['low']}-{vr['high']} vs current={vr.get('current_price')}")

    elif capability == "risk.analysis":
        for r in (content.get("detected_risks") or []):
            lines.append(f"{r['severity']}: {r['title']} ({r['detail']})")
        if not content.get("detected_risks"):
            lines.append("no threshold-based risks detected")

    elif capability == "earnings.call":
        lines.append(f"beats={content.get('beats')} misses={content.get('misses')} "
                     f"beat_rate={content.get('beat_rate')}")
        lines.append(f"consecutive_misses={content.get('consecutive_misses')}")

    elif capability == "filings.sec":
        lines.append(f"registrant={content.get('registrant_name')}")
        for form, fact in (content.get("filed_facts") or {}).items():
            lines.append(f"filed {form}={fact.get('value')} (FY{fact.get('fiscal_year')})")

    else:
        lines.append(ev.get("summary") or ev.get("citation") or "")

    rendered = "; ".join(str(line) for line in lines if line)
    return rendered[:1200]


def _format_claim_with_evidence(claim: dict, evidence_by_id: dict) -> str:
    cited = []
    for eid in (claim.get("evidence_ids") or [])[:3]:
        ev = evidence_by_id.get(eid)
        if not ev:
            continue
        cited.append(f"    [{eid}] {ev['capability']} -> {_render_evidence(ev)}")

    return (
        f"  CLAIM {claim['claim_id']}: {claim['text'][:400]}\n"
        f"  CITED EVIDENCE:\n" + ("\n".join(cited) or "    (none resolvable)")
    )


def check_hallucination(claims: list[dict], evidence_by_id: dict) -> SemanticResult:
    """Verify each claim follows from the evidence it cites."""
    result = SemanticResult()

    if not get_settings().openai_api_key:
        result.checks_skipped.append({
            "check": "hallucination",
            "reason": "no LLM configured -- claims were NOT verified against their evidence",
        })
        return result

    if not claims:
        result.checks_skipped.append({
            "check": "hallucination",
            "reason": "no interpretive claims were generated, so none required verification",
        })
        return result

    sample = claims[:MAX_CLAIMS_PER_CHECK]
    items = "\n\n".join(_format_claim_with_evidence(c, evidence_by_id) for c in sample)
    payload = _llm_json(_HALLUCINATION_PROMPT.format(items=items))

    if payload is None:
        result.checks_skipped.append({
            "check": "hallucination",
            "reason": "LLM unavailable -- claims were NOT verified",
        })
        return result

    result.checks_run.append("hallucination")
    for entry in payload.get("results", []):
        if entry.get("supported") is False:
            claim_id = entry.get("claim_id", "unknown")
            result.unsupported_claim_ids.append(claim_id)
            result.findings.append(_finding(
                "hallucination", Severity.BLOCKING,
                f"claim {claim_id} is not supported by its cited evidence: "
                f"{entry.get('reason', 'no reason given')}",
                claims=[claim_id],
            ))

    return result


def check_contradiction(claims: list[dict], filed_facts: dict | None = None) -> SemanticResult:
    """Detect claims that logically conflict with each other or with filed facts."""
    result = SemanticResult()

    if not get_settings().openai_api_key:
        result.checks_skipped.append({
            "check": "contradiction",
            "reason": "no LLM configured -- claims were NOT cross-checked for conflicts",
        })
        return result

    if len(claims) < 2:
        result.checks_skipped.append({
            "check": "contradiction",
            "reason": f"only {len(claims)} claim(s) present; contradiction requires at least two",
        })
        return result

    sample = claims[:MAX_CLAIMS_PER_CHECK]
    claims_text = "\n".join(f"  {c['claim_id']}: {c['text'][:300]}" for c in sample)

    facts_block = ""
    if filed_facts:
        facts_block = "Facts as filed with the SEC (authoritative):\n" + "\n".join(
            f"  {k}: {v.get('value')} (FY{v.get('fiscal_year')})" for k, v in filed_facts.items()
        )

    payload = _llm_json(
        _CONTRADICTION_PROMPT.format(claims=claims_text, filed_facts=facts_block)
    )

    if payload is None:
        result.checks_skipped.append({
            "check": "contradiction",
            "reason": "LLM unavailable -- claims were NOT cross-checked",
        })
        return result

    result.checks_run.append("contradiction")
    contradictions = payload.get("contradictions", [])
    result.contradiction_count = len(contradictions)

    for item in contradictions:
        result.findings.append(_finding(
            "contradiction", Severity.WARNING,
            f"contradiction detected: {item.get('explanation', 'unexplained')}",
            claims=item.get("claim_ids", []),
        ))

    return result


def run_semantic_checks(
    claims: list[dict], evidence_by_id: dict, filed_facts: dict | None = None
) -> SemanticResult:
    """Run both semantic checks and merge their outcomes."""
    hallucination = check_hallucination(claims, evidence_by_id)
    contradiction = check_contradiction(claims, filed_facts)

    return SemanticResult(
        findings=hallucination.findings + contradiction.findings,
        unsupported_claim_ids=hallucination.unsupported_claim_ids,
        contradiction_count=contradiction.contradiction_count,
        checks_run=hallucination.checks_run + contradiction.checks_run,
        checks_skipped=hallucination.checks_skipped + contradiction.checks_skipped,
    )
