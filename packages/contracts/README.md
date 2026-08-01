# irp-contracts

Reusable Pydantic schemas for multi-agent investment research workflows.

This package is the **shared seam** between independently deployed services
(LangGraph control plane, A2A specialists, CrewAI committee). It contains
**no framework dependencies** — only Pydantic — so it can be imported by any
Python service without dependency conflicts.

## Install

```bash
pip install -e packages/contracts
```

Or from a Dockerfile:

```dockerfile
COPY packages/contracts /app/packages/contracts
RUN pip install -e /app/packages/contracts
```

## What's included

| Module | Purpose |
|---|---|
| `evidence.py` | `Evidence`, `Claim` — citation-enforced facts |
| `plan.py` | `ResearchPlan`, `TaskSpec` — self-validating task DAG |
| `a2a.py` | `A2ATaskRequest`, `A2ATaskResult` — agent communication envelopes |
| `policy.py` | `apply_recommendation_gate()` — deterministic recommendation gating |
| `thesis.py` | `ThesisVersion`, `StructuredThesis` — versioned investment thesis |
| `safety.py` | `SafetyReport`, `CoverageReport` — safety pipeline output |
| `recommendation.py` | `Recommendation`, `CommitteePosition` |
| `report.py` | `InvestmentReport`, `ReportSection` |
| `industry_profiles/` | Industry-specific metrics, valuation methods, risk rules |
| `enums.py` | Capabilities, industry classifications, HITL decisions |

## Example

```python
from contracts import Claim, Evidence, SourceType, apply_recommendation_gate
from contracts import RecommendationAction, SafetyReport, CoverageReport
from datetime import datetime, timezone

# Claims cannot exist without evidence (enforced by Pydantic)
ev = Evidence(
    evidence_id="ev_abc",
    run_id="run_1",
    task_id="t1",
    agent_id="financial_analyst",
    capability="financials.ratios",
    source_type=SourceType.COMPUTED,
    source_name="financial_calculations",
    citation="Computed from yfinance Q3 2025",
    content={"pe_ratio": 32.4},
    retrieved_at=datetime.now(timezone.utc),
    confidence=0.9,
)

claim = Claim(
    claim_id="claim_1",
    run_id="run_1",
    text="P/E of 32.4 reflects premium valuation.",
    evidence_ids=[ev.evidence_id],
    confidence=0.85,
    polarity="neutral",
    category="valuation",
    author_agent_id="financial_analyst",
    created_at=datetime.now(timezone.utc),
)
```

## Tests

```bash
pytest packages/contracts/tests -v
```

## License

MIT — see [LICENSE](../../LICENSE) in the repository root.
