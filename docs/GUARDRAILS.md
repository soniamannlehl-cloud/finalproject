# Guardrails & validation reference

Where this platform enforces safety, and how failures are handled.

## Layer 1 — Structural (no LLM)

| Guardrail | Location | Behavior |
|-----------|----------|----------|
| Research plan DAG validation | `packages/contracts/plan.py` | Rejects cycles, unknown deps at plan build |
| Evidence IDs scoped per run | `packages/contracts/evidence.py` | Prevents cross-run evidence collision |
| Deterministic financial metrics | `specialists/.../financial_calculations.py` | LLM never computes numbers |
| Policy gate (Buy/Sell/Hold) | `packages/contracts/policy.py` | `MIN_EVIDENCE_SCORE`, confidence floors, contradictions |
| Recommendation synthesizer | `services/api/app/graph/nodes/synthesizer.py` | Applies gate; committee cannot bypass |
| Task retries + declared gaps | `services/api/app/director/director.py` | Failed optional tasks → gaps; required → lower score |
| Workflow caps | `services/api/app/config.py` | `max_replan_rounds`, `max_task_retries` |

## Layer 2 — Safety pipeline

| Check | Location | Behavior |
|-------|----------|----------|
| Coverage (required capabilities) | `services/api/app/safety/deterministic.py` | Failed required caps block directional calls |
| Citation integrity | deterministic safety | Claims must cite existing evidence IDs |
| Stale evidence | deterministic safety | Flags aged market/news data |
| Hallucination (semantic) | `services/api/app/safety/semantic.py` | LLM verifies claim ↔ evidence; reports NOT_CHECKED if skipped |
| Contradiction (semantic) | semantic.py | LLM flags incompatible claims |

## Layer 3 — Human-in-the-loop

| Checkpoint | Location | Behavior |
|------------|----------|----------|
| HITL #1 | `graph/nodes/validate.py` | User confirms company before research spend |
| HITL #2 | `graph/nodes/hitl_2.py` | User reviews report + recommendation; can replan or reject |

## Layer 4 — Agent constraints

| Agent | Constraint |
|-------|------------|
| Specialists | Handlers raise on provider failure; return flagged metrics when data missing |
| Committee | Debates only from capped `EvidenceBrief` — cannot invent off-brief facts |
| Thesis | Stance from signals first; framework from evidence only |
| Validation | LLM only when search returns no match (5 tokens max) |

## Error handling pattern

- **Graph nodes**: try/except → `{errors: [...]}`; non-fatal nodes (thesis) don't abort the run
- **Director**: retries with backoff; marks `FAILED` / `DEGRADED` / `SKIPPED`
- **A2A dispatch**: transport errors surfaced as `TaskState.FAILED`, not silent success
- **Committee / report**: degrade gracefully; safety failure can skip committee
- **No API key**: deterministic fallbacks throughout (plan, thesis, metrics, safety reports NOT_CHECKED)

## Multi-agent best practices (how this project maps)

| Practice | Implementation |
|----------|----------------|
| Separation of concerns | 3 services: orchestration / data / deliberation |
| Capability-based routing | Planner emits capabilities; Director discovers agents via A2A |
| Explicit planning artifact | `ResearchPlan` logged, versioned, UI-visible |
| Evidence traceability | Every claim → evidence IDs; report sources section |
| Refuse to act | `INSUFFICIENT_EVIDENCE` is first-class |
| Human approval gate | No finalize without HITL #2 |
| Bounded autonomy | Replan/validation/retry caps; no unbounded loops |
| Deterministic policy over LLM | Synthesizer + policy.py override committee |
| Graceful degradation | Optional tasks, provider fallbacks, keyless demo path |

## Gaps (honest)

- No rate-limit budget per run (token/$ cap) — only model tiering and brief caps
- Semantic safety skipped without API key (explicitly marked, not hidden)
- Some industry KPIs stubbed when data unavailable (flagged, not fabricated)
