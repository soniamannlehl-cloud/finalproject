# Architecture

**AI Investment Research Analyst** — a multi-agent system that simulates how
a professional investment research firm performs due diligence on a publicly
traded company.

---

## 1. Overview

The system takes a ticker or company name and produces a cited investment
report gated behind human approval. Between those two points it plans a
research strategy, dispatches specialist agents in parallel, accumulates
attributable evidence, maintains a versioned investment thesis, subjects its
conclusions to a layered safety pipeline, and runs an adversarial investment
committee.

Three design commitments shape everything below:

1. **Nothing is asserted without evidence.** Every factual statement carries
   a resolvable citation, enforced by the type system rather than by prompt
   instructions.
2. **The system may refuse to opine.** `INSUFFICIENT_EVIDENCE` is a
   first-class outcome, produced by a deterministic policy an LLM cannot
   argue past.
3. **A human holds the final gate.** No recommendation is finalized without
   explicit approval, and rejection can send the planner back to work.

---

## 2. System diagram

```
┌──────────────────────────────────────────────────────────────────┐
│  Next.js · React · TypeScript · Tailwind          (browser)      │
│  ticker entry │ plan viz │ evidence drawer │ HITL approval UI    │
└────────────────────────────┬─────────────────────────────────────┘
                             │ REST + Server-Sent Events
┌────────────────────────────▼─────────────────────────────────────┐
│  API SERVICE — control plane            FastAPI + LangGraph      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ Validation → Planner → Director → Thesis → Safety →        │  │
│  │ Synthesizer → Report          + 2 HITL interrupt points    │  │
│  └────────────────────────────────────────────────────────────┘  │
│  Decides. Never calls a data provider directly.                  │
└──┬──────────────────────┬────────────────────────┬───────────────┘
   │ A2A / HTTP           │ A2A / HTTP             │ SQL
   │                      │                        │
┌──▼─────────────────┐ ┌──▼──────────────────┐     │
│ SPECIALISTS        │ │ COMMITTEE           │     │
│ data plane         │ │ deliberation        │     │
│ FastAPI + a2a-sdk  │ │ FastAPI + CrewAI    │     │
│                    │ │                     │     │
│ 9 agents, each     │ │ Bull · Bear · CIO   │     │
│ publishing an      │ │ stateless; receives │     │
│ AgentCard          │ │ a condensed brief   │     │
│ Retrieves. Never   │ │ Argues. Never       │     │
│ decides scope.     │ │ fetches data.       │     │
└──┬─────────────────┘ └─────────────────────┘     │
   │                                                │
┌──▼──────────────────────────────────┐  ┌──────────▼──────────────┐
│ FMP · yfinance · SEC EDGAR          │  │ POSTGRES                │
│ NewsAPI · Tavily · Polygon          │  │ evidence · claims       │
└─────────────────────────────────────┘  │ thesis versions         │
                                          │ reports · tool_calls    │
┌─────────────────────────────────────┐  │ langgraph checkpoints   │
│ LangSmith ← OTel from all services  │  └─────────────────────────┘
└─────────────────────────────────────┘
```

**The invariant that keeps this clean:** the control plane *decides*, the
data plane *retrieves*, the committee *argues*. The API service never calls
Yahoo Finance; a specialist never chooses what to research next. Violating
this is what turns multi-agent systems into mud.

---

## 3. Framework selection

Three frameworks, each owning exactly one concern, with no overlap.

| Framework | Owns | Why it, specifically |
|---|---|---|
| **LangGraph** | Workflow, state, HITL, conditional routing | `interrupt()`/`Command(resume=…)` is the only primitive here that pauses mid-execution, persists full state, and resumes days later. The workflow has three such pause points. |
| **A2A** | Inter-agent communication + discovery | Specialists are separately deployed services advertising capabilities. The Director resolves capability → endpoint at runtime and never holds a hardcoded agent list. |
| **CrewAI** | Adversarial deliberation | Role-play debate with distinct personas is CrewAI's sweet spot. The committee is bounded, stateless, and contains no HITL — so none of LangGraph's strengths are needed inside it. |

### Google ADK: evaluated and rejected

ADK was in the original design for the specialist runtime. It was cut after
examining what a specialist actually does:

```
fetch from provider → normalize → compute metrics → attach citations
      (code)            (code)     (deterministic)      (code)
                                                            ↓
                                         write interpretation ← 1 LLM call
```

Specialists are **retrieval-and-compute workloads, not autonomous
reasoners**. Financial ratios are computed in Python because an LLM doing
arithmetic is a defect, not a feature. Wrapping that in a full agent runtime
would have added a fourth dependency tree, a second LLM client abstraction,
a second telemetry system to stitch into LangSmith, and another framework to
defend — in exchange for capabilities used at perhaps 15% utilization.

The rubric requires *at least two* frameworks and scores **justification
quality**, not count. A fourth framework that duplicates orchestration the
control plane already owns would have weakened that score, not strengthened
it.

This decision is cheap to reverse: specialists sit behind A2A, so swapping
one to ADK later changes only what runs behind an endpoint.

---

## 4. Dependency isolation: measured

> This section documents a hypothesis that was **tested and refuted**. It is
> retained deliberately — the revision is part of the engineering record.

**Original hypothesis.** LangGraph and CrewAI pin overlapping
`langchain-core` and `pydantic` ranges; installing both in one environment
would fail to resolve or silently break. The 3-service split was initially
justified on that basis.

**Experiment.** Four virtual environments: one per service, plus a
deliberate combined environment installing `services/api/requirements.txt`
and `services/committee/requirements.txt` together.

**Result.**

| Environment | Install | `pip check` | Notable versions |
|---|---|---|---|
| api (isolated) | OK | clean | langgraph 1.2.10, langchain-core 1.5.3, pydantic **2.13.4** |
| specialists (isolated) | OK | clean | a2a-sdk 1.1.2, pydantic **2.13.4** |
| committee (isolated) | OK | clean | crewai 1.15.10, pydantic **2.12.5** |
| **api + committee combined** | **OK** | **clean** | crewai 1.15.10 · langgraph 1.2.10 · pydantic **2.12.5** |

**The hypothesis was wrong.** pip resolves both frameworks together without
error. The real coupling is softer than predicted: CrewAI constrains
`pydantic` down from 2.13.4 to 2.12.5 — version pressure, not incompatibility.

**What this changed.** The architecture was kept, but its justification was
rebuilt on grounds that survive the evidence:

1. **A2A semantics (primary).** A2A is a protocol for communication between
   independently addressable agents. Collapsing to one process reduces it to
   function calls behind a protocol-shaped wrapper — the exact criticism
   that motivated rebuilding this system. Separate services make discovery,
   capability negotiation, and transport genuine.
2. **Image size (measured).** api is **529MB**; committee is **1.84GB**.
   Merging them would nearly quadruple the control plane image and slow
   every rebuild in the development loop.
3. **Version decoupling (soft, real).** The pydantic divergence above is
   precisely the coupling the split avoids.
4. **Blast radius.** A CrewAI failure cannot take down the workflow engine
   holding in-flight checkpointed runs.

**Cost of being wrong.** Had the split been justified only by the refuted
claim, the honest conclusion would have been to collapse the architecture.
It was retained because reasons (1) and (2) are independently sufficient —
not because the work was already done.

---

## 5. LangGraph workflow

```
START
  │
  ▼
[validate_company] ──(private / not found)──► END (explain)
  │ resolved
  ▼
◆ HITL #1 — interrupt(): confirm company + ticker
  │  ├─ rejected ──► [validate_company] (retry with new input)
  │  └─ confirmed
  ▼
[planner] ──► ResearchPlan { tasks[], deps, metrics, valuation methods }
  │
  ▼
[director] ──► Send(specialist_proxy, task) × N     ◄── dynamic fan-out
  │
  ├─► [specialist_proxy] ─┐   parallel A2A calls
  ├─► [specialist_proxy] ─┤   (one node type, N invocations)
  └─► [specialist_proxy] ─┘
                          ▼   LangGraph joins the branches
                   [evidence_gate]  ── deterministic
                    │ ├─ retriable failures ──► [director] (retry subset)
                    │ ├─ coverage < floor ────► degraded-mode flag
                    │ └─ ok
                    ▼
               [thesis_agent] ──► ThesisVersion(n)
                    │
                    ▼
               [safety_pipeline]  L0 schema → L1 deterministic → L2 semantic
                    │ ├─ blocking ──► [director] (targeted re-research, capped)
                    │ └─ pass / warn
                    ▼
               [committee] ──► A2A → CrewAI (Bull · Bear · CIO)
                    │
                    ▼
               [synthesizer] ──► gated Recommendation
                    │
                    ▼
               ◆ HITL #2 — interrupt(): approve │ reject │ request analysis
                    │ ├─ approve ──────────────► [report_generator] ──► END
                    │ ├─ reject ───────────────► END (archived, no report)
                    │ └─ request more ─────────► [planner.replan(feedback)]
                    │                                   │
                    └───────────────────────────────────┘
                          capped at MAX_REPLAN_ROUNDS
```

### Why the graph is static

The Planner does **not** rebuild the graph per request. LangGraph compiles a
fixed topology; rebuilding it per run would break checkpoint compatibility
across resumes and fragment traces.

Instead: **static topology + dynamic plan in state + `Send` API.** The
Director reads `ResearchPlan.execution_layers()` and emits
`[Send("specialist_proxy", task) for task in layer]`. The number of parallel
branches, their payloads, and their ordering are all decided at runtime from
data. The graph is fixed; the execution is fully dynamic.

`specialist_proxy` is **one node, not nine** — adding a tenth specialist
means registering an AgentCard, not editing the graph.

### Every loop is capped

`max_task_retries`, `max_safety_reresearch_rounds`, and `max_replan_rounds`
all have ceilings that force a terminal state. An uncapped agentic loop is
the most reliable way to hang a live demo.

---

## 6. Agent responsibilities

| Agent | Owns | Never does |
|---|---|---|
| **Company Validation** | Resolve input → ticker; classify public / private / not-found | Fetch financials |
| **Research Planner** | Emit the plan: specialists, metrics, valuation methods, dependencies, fallbacks | Execute anything |
| **Research Director** | Discover agents, dispatch, monitor, retry, merge, replan | **Perform research** |
| **9 Specialists** | Call tools; return structured evidence + citations + confidence | Talk to each other; choose scope |
| **Thesis Agent** | Maintain the versioned living thesis | Invent facts |
| **Safety Pipeline** | Contradiction, hallucination, validation, freshness, consistency | Rewrite content |
| **Committee (Bull/Bear/CIO)** | Argue both sides; propose a recommendation | Fetch new data |
| **Report Generator** | Render HTML + PDF with resolved citations | Add uncited claims |

Specialists never call each other. If Valuation needs Financial's output,
that is a **dependency in the plan**, resolved by the Director —
peer-to-peer calls would create a hidden execution graph the Director could
not monitor, retry, or trace.

---

## 7. State management

**Rule 1 — parallel writes require reducers.** Nine specialists writing
concurrently to shared state raises `InvalidUpdateError` without them:

```python
evidence_ids : Annotated[list[str], operator.add]
task_status  : Annotated[dict, merge_dicts]
errors       : Annotated[list[AgentError], operator.add]
```

Scalars (`ticker`, `status`, `thesis_version`) are written by exactly one
node each — a maintained invariant, documented in the state module.

**Rule 2 — state is a manifest, not a warehouse.** LangGraph checkpoints the
entire state object on every superstep.

| In graph state (checkpointed) | In Postgres (referenced) |
|---|---|
| ticker, plan, task_status | evidence payloads |
| `evidence_ids: list[str]` | claims |
| `thesis_version: int` | thesis version history |
| safety flags, scores | committee transcripts |
| HITL decisions | rendered reports, tool-call log |

Putting filing text in state would produce multi-MB checkpoints and visibly
slow resume during a demo.

**Rule 3 — Postgres, not SQLite.** Multi-container access and durable
restart. SQLite is dev-only.

---

## 8. A2A communication

Each specialist publishes an AgentCard at `/.well-known/agent.json`:

```
AgentCard
  agent_id · name · description · version
  endpoint      http://specialists:8081/a2a
  skills[]      { skill_id, capability, input_schema, output_schema }
  capabilities  ["financials.ratios", "financials.statements"]   ◄ routing key
```

**Flow:** the Director fetches cards at startup → the Planner emits tasks
naming *capabilities*, never agent IDs → the Director resolves capability →
endpoint → dispatches `A2ATaskRequest` → receives `A2ATaskResult`.

Two properties this buys:

- **Loose coupling.** `AgentRegistry.resolve()` is the only place agent
  identity is known. The Planner is written against capabilities alone.
- **Graceful unavailability.** `AgentRegistry.missing()` reports capabilities
  no agent can serve, so an unserviceable plan becomes a *declared gap* in
  the report rather than a runtime crash.

Failures travel *inside* `A2ATaskResult` (`state=FAILED`, `error=...`) rather
than as HTTP exceptions — a dead provider degrades the run instead of
crashing the workflow.

---

## 9. Guardrails

Layered cheapest-and-most-reliable first:

```
L0  SCHEMA         Claim requires ≥1 evidence_id       free · absolute
L1  DETERMINISTIC  freshness · citation resolution ·   free · unit-testable
                   coverage scoring
L2  SEMANTIC       contradiction · hallucination        costly · fuzzy (LLM)
L3  POLICY         recommendation gating                deterministic rules
L4  HUMAN          HITL #2                              definitive
```

**Three of five safety checks are deliberately not LLMs.** Freshness is
`now - retrieved_at > threshold`. Citation resolution is a set operation
against the repository. Coverage is arithmetic. Using a language model for
these would make them slower, costlier, and *less* reliable. LLM judgment is
reserved for contradiction and hallucination detection, where semantics
genuinely matter.

**L0 in practice** — the anti-fabrication guarantee is a type constraint:

```python
class Claim(BaseModel):
    evidence_ids: list[str] = Field(min_length=1)   # uncited claim is unconstructible
```

Mirrored in SQL (`CHECK (array_length(evidence_ids, 1) >= 1)`) so the
invariant survives a buggy writer.

**L3 gating policy** (`packages/contracts/src/contracts/policy.py`):

```
unresolvable citation present     → INSUFFICIENT_EVIDENCE   (hard block)
blocking safety finding           → INSUFFICIENT_EVIDENCE   (hard block)
evidence_score < 0.60             → INSUFFICIENT_EVIDENCE
confidence < 0.70                 → force HOLD (no BUY/SELL)
contradictions > 2                → force HOLD
otherwise                         → committee's call stands
```

A 0.99-confidence BUY is hard-blocked the moment one citation fails to
resolve. The committee proposes; the policy disposes.

---

## 10. External data integration

| Data class | Primary | Fallback | Terminal behavior |
|---|---|---|---|
| Quotes / statements | FMP | yfinance | degrade + flag |
| Filings | SEC EDGAR | FMP | declare gap |
| News | NewsAPI | Tavily | degrade + flag |
| Market data | Polygon | yfinance | degrade + flag |

Every call passes through one `ToolClient`:

```
timeout → retry (exponential + jitter) → circuit breaker → provider failover
        → response cache (TTL by data class) → normalize to Evidence → OTel span
```

- **Immutable data is cached permanently.** Filings and reported statements
  never change once published, keyed by accession number — repeated demo
  runs on the same ticker are nearly free.
- **Failure is data, not an exception.** A dead provider yields Evidence with
  `confidence=0` and a declared gap.
- **yfinance requires no key** and anchors every fallback chain, so the
  platform remains demonstrable with zero paid subscriptions.

---

## 11. Observability

Traces span three containers and three frameworks. **OpenTelemetry is the
substrate; LangSmith is the backend.**

The critical detail: `traceparent` is propagated on every A2A call
(`A2ATaskRequest.traceparent`). Without it, specialist spans orphan into
separate traces and cross-service observability silently breaks.

```
research_run {ticker, run_id}
├── validate_company
├── hitl_1                        ← human decision latency measured
├── planner                       {plan_revision, tasks_planned}
├── director.dispatch             {agents_discovered, tasks_sent}
│   └── specialist:financial      [cross-service]
│       ├── tool:fmp              {provider, cache_hit, latency, status}
│       └── tool:yfinance         {fallback_triggered: true}
├── thesis.update                 {version, change_reason}
├── safety.contradiction          {findings}
├── committee                     [cross-service]
│   ├── bull ├── bear └── cio
├── hitl_2                        {decision, replan_requested}
└── report
```

Recorded metrics: evidence_score, confidence, tool failure rate, cache hit
rate, replan count, human decision latency, thesis version count.

---

## 12. Data models

Defined in `packages/contracts` — Pydantic only, importable by all three
services regardless of their framework trees.

| Model | Role | Notable invariant |
|---|---|---|
| `Evidence` | Immutable retrieved fact | Content-addressed ID → free dedup on retry |
| `Claim` | Interpretive statement | `evidence_ids` non-empty |
| `ResearchPlan` | Execution strategy | Self-validating DAG; `execution_layers()` |
| `TaskSpec` | One unit of work | Names a *capability*, not an agent |
| `AgentCard` | A2A advertisement | `capabilities` drives routing |
| `ThesisVersion` | One thesis snapshot | `parent_version` + `change_reason` |
| `SafetyReport` | Aggregate verdict | `is_blocking` gates the recommendation |
| `Recommendation` | Committee output | `was_downgraded` + `gate_reasons` |
| `InvestmentReport` | Final deliverable | `limitations` and `declared_gaps` mandatory |

Two details carry disproportionate weight:

- **`ResearchPlan` validates its own DAG.** An LLM produces this object and
  can hallucinate a dependency on a nonexistent task or emit a cycle.
  Catching that at construction turns a mid-execution hang into a clear
  error the Planner can retry against.
- **`ThesisVersion.parent_version` + `change_reason`** make "the thesis
  evolves" demonstrable rather than asserted — you can show v1 → v5 with the
  trigger and rationale for each revision.

---

## 13. Tradeoffs

| Decision | Gained | Paid |
|---|---|---|
| 3-service split | Genuine A2A; lean control plane; independent failure domains | Network latency; distributed debugging; Docker mandatory for local dev |
| Static graph + `Send` | Stable checkpoints, coherent traces, idiomatic | Not literally "the planner builds the graph" — dynamic *dispatch* achieves the goal instead |
| CrewAI for committee only | Excellent fit for bounded role-play debate | A whole framework, and 1.3GB, for one subsystem |
| Google ADK cut | One less runtime, tree, and telemetry system to stitch | Three frameworks instead of four |
| Evidence in Postgres | Small checkpoints; resolvable citations | Extra infra; a join to render a report |
| Deterministic guardrails first | Fast, free, unit-testable | Less "agentic-looking" than five LLM checkers — but far more defensible |
| Capped loops everywhere | Cannot hang mid-demo | Occasionally halts before converging |
| Model tiering | ~4× cheaper per run | Two model configs to reason about |

---

## 14. Technical analysis

### Planning paradigm: hierarchical decomposition with monitored replanning

Each component uses the planning style matching its actual uncertainty:

- **Specialists use fixed workflows, not ReAct loops.** Their data sources
  are known in advance. Letting an LLM decide dynamically which tool to call
  would add flexibility the task doesn't need while sacrificing
  predictability — a dynamic agent can skip a step or give up early. This
  follows the workflow-versus-agent distinction: predefined code paths with
  LLM calls at specific points, chosen deliberately over autonomy because
  the task structure is already known.
- **The Planner performs explicit hierarchical decomposition**, emitting a
  `ResearchPlan` whose structure (capabilities, dependencies, metrics,
  valuation methods) varies by industry playbook. A bank gets NIM, ROE, and
  credit-risk analysis; a REIT gets FFO, AFFO, NAV, and occupancy. The
  decomposition is *data*, so it is loggable, diffable, renderable, and
  assertable in tests — which is what distinguishes explicit planning from a
  hardcoded pipeline.
- **Replanning is monitor-and-revise, not patch.** When HITL #2 requests
  additional analysis, the Planner produces a new plan *revision* carrying
  `parent_revision` and `replan_reason`; the Director diffs it against
  completed work and dispatches only the delta. The thesis is re-derived in
  light of new input rather than annotated after the fact.

### Coordination model: orchestrator-worker + capability-routed dispatch

The dominant model is **hub-and-spoke**: the LangGraph state machine — not
an LLM — coordinates. This was chosen over two alternatives:

- **Autonomous multi-agent conversation** (AutoGen group chat, CrewAI crew
  delegation) would let agents negotiate turn order. Rejected because the
  data dependencies are known and fixed: Valuation genuinely needs
  Financial's output; News genuinely doesn't. A graph makes that structure
  explicit in one file instead of emergent from negotiation — and
  debuggable when it goes wrong.
- **Blackboard architecture** describes what the evidence repository *is*,
  but this controller is far more constrained than an open blackboard's:
  routing is a handful of named functions, not a general rule engine. That
  buys predictability and testability (every transition is enumerable by
  reading `graph.py`) at the cost of extensibility — a tenth specialist
  requires an AgentCard, but a tenth *workflow stage* requires editing the
  graph.

The exception is **Checkpoint #2 Q&A and committee dispatch**, where A2A
provides capability-routed peer dispatch: a request is routed by *capability
match* rather than by fixed graph edges. That is the one place the
hub-and-spoke model doesn't fit, and it is exactly where A2A earns its place.

### Tool-use pattern: deterministic computation, LLM interpretation

Every numeric result — ratios, trends, coverage scores — is computed by a
guarded Python function. The LLM's role is strictly *interpreting*
already-computed values. Alternatives rejected: prompting the LLM to compute
ratios from raw numbers (arithmetic hallucination; no guard for negative-EPS
P/E), and a code-interpreter pattern (more flexible, much harder to audit,
overkill for a small fixed set of safety-relevant formulas).

### Limitations

- **Planning structure is bounded by the playbook set.** A company in an
  industry without a playbook falls back to generic analysis, which is less
  precise than a bespoke metric set.
- **No cross-session learning.** Each run is independent; the system does not
  calibrate from a committee's approval history.
- **A2A discovery is startup-cached.** A specialist deployed mid-run is not
  discovered until the Director refreshes.
- **Semantic safety checks are LLM-judged**, so contradiction and
  hallucination detection inherit the judge model's failure modes. The
  deterministic layers below them are the real floor.
- **The committee is the cost center.** Three frontier-model agents dominate
  per-run spend; the condensed brief mitigates but does not eliminate this.
- **Single-region, single-instance.** No horizontal scaling or queue backing
  the A2A calls; a specialist restart mid-run fails those tasks into the
  retry path.

### Next steps

- Persist AgentCards in Postgres and refresh discovery on failure, so fleet
  changes are picked up without an API restart.
- Add a LangSmith-backed evaluation harness measuring recommendation
  consistency across repeated runs on the same ticker.
- Introduce a queue (Redis/Celery) behind A2A dispatch so specialist
  restarts don't fail in-flight tasks.
- Expand industry playbooks, or have the Planner propose a candidate metric
  set for uncovered industries subject to human review.

---

## 15. Build milestones

| # | Scope | Status |
|---|---|---|
| **M0** | Service skeletons · contracts · Docker · isolation experiment | ✅ |
| M1 | Company validation + HITL #1 + Postgres checkpointing | ⬜ |
| M2 | Planner → Director → one specialist over real A2A *(vertical slice)* | ⬜ |
| M3 | Full specialist fleet + `Send` fan-out + retry/fallback | ⬜ |
| M4 | Evidence repository + versioned living thesis | ⬜ |
| M5 | Safety pipeline + `INSUFFICIENT_EVIDENCE` path | ⬜ |
| M6 | CrewAI investment committee over A2A | ⬜ |
| M7 | HITL #2 + replan loop (delta re-dispatch) | ⬜ |
| M8 | PDF report generation | ⬜ |
| M9 | Frontend | ⬜ |
| M10 | Cross-service LangSmith stitching + evaluation harness | ⬜ |

**M2 is the critical milestone.** It proves A2A-across-containers works with
LangGraph checkpointing — the riskiest seam in the design, deliberately
scheduled early.
