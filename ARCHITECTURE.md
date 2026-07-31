# Architecture

## Overview

The Collaborative Investment Research Platform is a multi-agent LangGraph
system that researches a publicly traded company across three dimensions
(sentiment, financials, macro/industry) and synthesizes the findings into a
beginner-friendly memo plus a draft investment recommendation. The
recommendation is never surfaced to an end investor or treated as final --
it is drafted *for* a human investment committee, who must explicitly
approve it, reject it, or send it back for revision (with feedback the
Orchestrator uses to update its thesis) before anything is finalized. Two
other human-in-the-loop checkpoints keep the user in control: confirming
the company before research starts, and a hard-stop retry offer if all
research fails.

## System diagram

```mermaid
flowchart TD
    START([user input]) --> Intake[Intake & Validation Agent]
    Intake -- "no match / rejected" --> ENDTURN([turn ends -- retry next message])
    Intake -- "Checkpoint #1: confirm Y/N" -.->|interrupt| Intake

    Intake -- confirmed --> Sentiment[Sentiment Analyst]
    Intake -- confirmed --> IndustryID[Industry Identification -- deterministic]

    IndustryID --> Financial[Financial Analyst]
    IndustryID --> Macro[Macro & Industry Analyst]
    Sentiment --> Sync[sentiment_sync -- no-op depth barrier]

    Sync --> DataCheck{Data Failure Check}
    Financial --> DataCheck
    Macro --> DataCheck

    DataCheck -- "1-2 failed: pass through" --> BuildMemo[Orchestrator: build memo + recommendation]
    DataCheck -- "3/3 failed" -.->|interrupt: total failure| DataCheck
    DataCheck -- "retry" --> Sentiment

    BuildMemo --> Checkpoint2[Checkpoint #2: committee approval]
    Checkpoint2 -- "question" -->|A2A route_question| Specialist[owning specialist's answer_question]
    Specialist --> Checkpoint2
    Checkpoint2 -- "revise + feedback" --> BuildMemo
    Checkpoint2 -- "approve / reject" --> END([complete])
```

`sentiment_sync` is a trivial no-op node -- see **Engineering tradeoffs**
for why it exists. `industry_identification` runs in parallel with
Sentiment Analyst and feeds Financial and Macro & Industry Analyst, exactly
as specified: those two specialists genuinely wait on it.

## Node walkthrough

| Node | Type | Notes |
|---|---|---|
| `intake_validation` | LLM agent | Ticker/company search, LLM extraction pre-step for freeform phrasing ("the Delta situation"), LLM classification (private vs. not-found) when no match is found. Owns Checkpoint #1. |
| `industry_identification` | Deterministic | No LLM call -- yfinance `.info` sector/industry lookup. Runs in parallel with Sentiment Analyst, feeds Financial and Macro & Industry Analyst. |
| `sentiment_analyst` | LLM agent | News search (`scope="company"`), flags low-coverage deterministically. |
| `sentiment_sync` | Deterministic no-op | Depth-equalizing barrier -- see Engineering tradeoffs. |
| `financial_analyst` | LLM agent + deterministic math | Waits on `industry_identification`. yfinance primary / Alpha Vantage fallback for raw data; ratios computed by `tools/financial_calculations.py` (never by the LLM); LLM only interprets the results. Flags stale/incomplete filings. |
| `macro_industry_analyst` | LLM agent + deterministic math | Waits on `industry_identification`. FRED indicators + trend, sector ETF performance vs. S&P 500 (`tools/macro_calculations.py`), industry-specific indicators from `data/sector_indicators.json`, qualitative industry landscape via news search. |
| `data_failure_check` | Deterministic | The only data-related interrupt: hard-stops and offers retry only when all 3 specialists fail. |
| `build_memo` | LLM agent (Orchestrator) | 5 separate LLM calls for the explicit reasoning chain (evidence pattern -> risk factors -> invalidation triggers -> catalysts/timeline -> draft recommendation), each independently inspectable in LangSmith traces, followed by one synthesis call for the beginner-friendly memo. On a revision round, re-runs all 5 with the committee's feedback injected into every prompt. |
| `checkpoint_2_review` | LLM agent (Orchestrator) | Loops on `interrupt()` for open-ended Q&A (A2A-routed), then requires a genuine committee decision -- approve, reject, or revise + feedback -- to exit. |

## Framework justification

### LangGraph with HITL

LangGraph's `interrupt()` / `Command(resume=...)` pattern is the backbone.
It was chosen because the product requirement is fundamentally about
*pausing exactly where a human decision belongs* -- confirming a company
match, and gating a recommendation behind committee approval -- without
losing the state already gathered (specialist outputs, reasoning chain,
Q&A history, revision history). A SQLite checkpointer persists this state
across turns, so a multi-message conversation (confirm -> research ->
review -> ask questions -> revise -> re-review -> approve) is really one
checkpointed graph run resumed repeatedly.

### A2A Protocol (lightweight, in-process)

The brief calls for A2A specifically to route Checkpoint #2 follow-up
questions to the specialist that owns the topic, not a generic Orchestrator
answer. A full A2A deployment (`python-a2a` or similar) exposes each agent
as an HTTP service with a published `AgentCard` at a well-known URL --
useful when specialists are independently deployed processes, but this
system runs all 3 specialists in one LangGraph process. `tools/a2a_router.py`
keeps A2A's actual conceptual pieces -- `AgentCard` (identity + owned
topics), `A2AMessage` (the routed request/response envelope), and
capability-based routing -- but dispatches in-process via a handler
registry instead of network calls. `route_question()` tries deterministic
keyword matching against each card's topics first (fast, free, inspectable
in traces) and only falls back to an LLM classification call when no
keyword matches, since natural-language phrasing doesn't always contain an
obvious keyword.

### Why not CrewAI, Google ADK, or n8n

- **CrewAI** models multi-agent work as a crew of role-based agents
  executing a task list, but its native HITL story is thinner than
  LangGraph's -- there's no first-class equivalent of `interrupt()` that
  pauses and resumes arbitrary graph state mid-execution, which this
  system needs repeatedly (Checkpoint #1, the multi-turn Checkpoint #2 Q&A
  loop, and the revise -> re-review cycle). Bolting that on would mean
  reimplementing what LangGraph already provides.
- **Google ADK** is a capable agent framework, but adopting it alongside
  LangGraph would mean two orchestration frameworks doing the same job
  (graph/state management) for no added capability here -- the brief caps
  framework count at exactly 2 (LangGraph + A2A), and ADK isn't needed for
  either the HITL backbone or the specialist-routing requirement.
- **n8n** is a visual workflow/automation tool aimed at connecting SaaS
  triggers and actions, not at fine-grained agentic state machines with
  typed state, conditional fan-out/fan-in, and mid-execution human
  checkpoints. It's the wrong level of abstraction for this system's core
  requirement (a stateful, resumable multi-agent reasoning graph).

## HITL checkpoint design

1. **Checkpoint #1 (Company Validation)** -- *always* interrupts on a
   match, not just ambiguous ones, per the brief. "No" or no-match ends
   that graph turn; because there's no frontend in this build, the next
   `invoke()` call (same `thread_id`) starts a fresh attempt rather than
   nesting a second `interrupt()` inside the same node call.
2. **Checkpoint #2 (Investment Committee Approval)** -- one node loops on
   `interrupt()` for as many follow-up questions as the committee has, each
   dispatched via A2A to the owning specialist and appended to
   `checkpoint_2_qa_history`. It only exits on a genuine decision:
   - **Approve** or **reject** end the session; the recommendation is
     finalized only on approval.
   - **Revise** requires feedback and routes back to `build_memo`, which
     re-runs its full 5-step reasoning chain with that feedback injected
     into every prompt -- a real update to the thesis, not a cosmetic
     reword -- then re-presents an updated Checkpoint #2. Capped at
     `MAX_REVISION_ROUNDS` (default 3) to prevent an infinite loop; past
     that, the session auto-closes as rejected.
   This is a genuine decision point, not a rubber stamp: "revise" visibly
   and measurably changes the next `draft_recommendation`, `risk_factors`,
   and `headline_finding`.
3. **Total data failure** -- the only data-related interrupt; 1 or 2
   specialist failures pass through silently to the Orchestrator, which
   discloses the gap in the memo (`data_gaps`) instead of interrupting the
   user over a partial result.

## Non-negotiable principles, enforced in code (not just prompted)

- **Recommendation gated behind human approval**: the draft recommendation
  is written for the committee's review only -- every prompt that produces
  it explicitly frames it as a draft for approval, never advice addressed
  to an individual end investor, and the graph has no path that finalizes
  it without a human `approve` decision at Checkpoint #2.
- **Deterministic math, never LLM arithmetic**: every ratio and trend has
  its own guarded Python function (`tools/financial_calculations.py`,
  `tools/macro_calculations.py`); the LLM only ever receives
  already-computed values to interpret.
- **No persistent user profile**: nothing about the user (risk tolerance,
  goals) is stored anywhere in `state.py` or the checkpointer -- only the
  research, the committee's decisions, and feedback for that session.
- **Transparent failure disclosure**: low sentiment coverage, stale/
  incomplete filings, and partial specialist failures are flagged with a
  deterministic prefix in the relevant text field (not left to the LLM's
  discretion to remember to mention).
- **A2A-routed Q&A**: every Checkpoint #2 question is dispatched to a
  specific specialist's `answer_question()`, never answered generically by
  the Orchestrator.
- **Revision must change behavior**: `committee_feedback` is injected into
  every one of the Orchestrator's 5 reasoning-step prompts on a revise
  round, and `revision_count` is tracked in state -- a revise decision is
  never silently logged and ignored.

## Engineering tradeoffs

- **`sentiment_sync`: a no-op depth-equalizing barrier.** Industry
  Identification runs in parallel with Sentiment Analyst and feeds
  Financial and Macro & Industry Analyst, per the intended design -- but
  that shape is an asymmetric-depth diamond: Sentiment's path reaches
  `data_failure_check` in 1 hop from the fan-out, while Financial/Macro's
  path takes 2 hops (via `industry_identification`). Isolated minimal
  repros showed this specific asymmetry -- not the diamond shape itself --
  reproducibly corrupts execution in LangGraph 1.2.10 once combined with
  the multi-interrupt Checkpoint #2 loop downstream (an `InvalidUpdateError`
  on a shared state channel, or with a permissive reducer, a spurious
  duplicate interrupt on an already-closed session). Making Sentiment's
  path pass through one trivial no-op node (`sentiment_sync`) so all 3
  specialist paths arrive at `data_failure_check` at the same depth
  resolved it completely, while keeping the intended topology (a real
  `industry_identification` node, Financial/Macro genuinely waiting on it)
  intact. This is purely a defensive workaround for this LangGraph
  version's synchronization assumptions, not a product design choice.
- **NewsAPI primary, Alpha Vantage NEWS_SENTIMENT fallback.** Reuses the
  Alpha Vantage key already needed for the financial-data fallback rather
  than requiring a third API signup, at the cost of AV's fallback path
  sharing its tight rate limit (25 req/day) with financial data.
  Alpha Vantage's fixed topic taxonomy also can't do free-text industry
  search, so the industry-scope fallback uses a best-effort topic mapping
  and degrades to AV's general feed when no mapping exists.
- **Industry-specific ratio/indicator tables cover common industries, not
  the full yfinance taxonomy.** `data/industry_ratios.json` and
  `data/sector_indicators.json` key on yfinance's finer-grained `industry`
  string with a sector-level fallback, covering the industries a beginner
  investor is most likely to research (banks, airlines, tech, pharma,
  retail, energy, utilities, REITs, etc.) rather than attempting exhaustive
  coverage of yfinance's hundreds of industry values.
- **Alpha Vantage's fallback path doesn't populate industry/sector** --
  its OVERVIEW endpoint reports them in a different taxonomy/casing than
  yfinance, which wouldn't match the lookup tables anyway, so a
  fallback-sourced company gets universal ratios only rather than values
  that look plausible but silently fail to match.

## Technical Analysis

### Planning paradigm: fixed workflow decomposition, not autonomous ReAct

Two different planning styles were available for this system, and each
agent uses the one suited to its actual uncertainty:

- **Specialist agents (Sentiment, Financial, Macro & Industry) use a fixed
  workflow, not a ReAct-style tool-calling loop.** Each specialist's data
  sources are known in advance -- Sentiment always calls `news_search`;
  Financial always tries yfinance then Alpha Vantage then its own ratio
  functions. Letting an LLM decide dynamically which tool to call and when
  (the classic ReAct "reason, act, observe" loop) would add flexibility
  this task doesn't need, at the cost of predictability: a dynamic agent
  could skip a step, call tools in a nonsensical order, or silently give up
  early. This follows the "workflow vs. agent" distinction from Anthropic's
  effective-agents framing -- predefined code paths with LLM calls at
  specific points, chosen deliberately over full autonomy because the task
  structure is already known.
- **The Orchestrator uses explicit hierarchical task decomposition**, not a
  single opaque "write the memo" call: `build_memo_node` runs 5 named,
  sequential reasoning steps (evidence pattern -> risk factors ->
  invalidation triggers -> catalysts/timeline -> draft recommendation),
  each its own LLM call and its own LangSmith span, with later steps
  explicitly given earlier steps' output as context (step 3 is handed
  steps 1 and 2's text directly). This is closer to a fixed
  goal-decomposition template than a fully dynamic planner (see
  Limitations) -- the five-step *structure* is hard-coded, but each step's
  *content* is fully LLM-generated from live data, which is what makes it
  inspectable rather than hard-coded output.
- **The revise cycle is a monitor-replan loop, not a patch.** When the
  committee sends feedback, `build_memo_node` doesn't append a correction
  to the old output -- it re-runs the entire 5-step decomposition with the
  prior recommendation and the committee's feedback injected into every
  single prompt, so the thesis is genuinely re-derived in light of new
  information. This is the course's "planning: building and updating an
  investment thesis as new data arrives" requirement in its most literal
  form: the "new data" is human feedback, and the system replans rather
  than just reprinting the old plan with a note attached.

### Coordination model: hub-and-spoke workflow + capability-routed peer dispatch

The dominant coordination model is **hub-and-spoke / orchestrator-worker**:
Intake, the 3 specialists, and the Orchestrator are wired through one
LangGraph `StateGraph`, sharing a single typed state schema
(`InvestmentResearchState`), with the *graph itself* -- not an LLM -- acting
as coordinator. This was chosen over two alternatives:

- **A fully autonomous multi-agent conversation** (AutoGen's group-chat
  pattern, or CrewAI's crew delegation, where agents negotiate turn order
  among themselves) would add real complexity for no benefit here, because
  the task's data dependencies are already known and fixed (Financial and
  Macro genuinely need `industry` before they can run; Sentiment doesn't).
  A graph-based workflow makes that dependency structure explicit and
  inspectable in one file (`graph.py`) instead of emergent from agent
  negotiation.
- **A blackboard architecture** (shared state any agent can read/write,
  with a controller dynamically deciding who runs next based on state
  contents) is actually a reasonable description of what `InvestmentResearchState`
  *is* -- but our controller (the graph's conditional edges) is far more
  constrained than an open blackboard's would be: routing decisions are a
  small set of named functions (`route_after_intake`, `route_after_data_check`,
  `route_after_checkpoint_2`), not a general rule engine that could route
  to an arbitrary next agent based on arbitrary state. This buys
  predictability and testability (every possible transition is enumerable
  by reading `graph.py`) at the cost of extensibility -- adding a 6th
  specialist means editing the wiring by hand, not just registering a new
  agent with the blackboard.

For the one place where the hub-and-spoke model doesn't fit -- Checkpoint
#2 Q&A, where a human question needs to reach whichever specialist
actually owns the topic -- a **capability-routed peer-dispatch layer** (A2A)
sits on top of the graph. `route_question()` matches the question against
each specialist's declared topics (an `AgentCard`), then dispatches
directly to that specialist's `answer_question()`, bypassing the
Orchestrator. This is architecturally different from the rest of the
system: it's the one place a "request" is routed by *capability match*
rather than by fixed graph edges. Real A2A deployments make this literal --
each agent is an independently addressable network service; here it's
in-process, which is the right tradeoff when every agent is one deployment
unit, but would need to become a real networked layer if specialists were
ever owned by different teams or needed independent scaling.

### Tool-use pattern: deterministic computation, LLM interpretation only

Every numeric calculation (financial ratios, macro trends, sector ETF
performance) is computed by a hand-written, guarded Python function --
never by asking the LLM to do arithmetic. The LLM's role is strictly
*interpreting* already-computed values (`tools/financial_calculations.py`'s
docstring is explicit about this). This was chosen over two alternatives:
prompting the LLM to compute ratios directly from raw numbers (risks
arithmetic hallucination, and provides no guard for edge cases like
negative EPS), or a code-interpreter pattern where the LLM writes and
executes its own calculation code (more flexible, but harder to audit and
overkill for a small, fixed, safety-relevant set of formulas). Guarded,
named functions are both simpler to verify and directly testable in
isolation, which is why `tools/financial_calculations.py` and
`tools/macro_calculations.py` were unit-tested against real yfinance/FRED-shaped
data before being wired into any agent.

### Limitations

- **The reasoning-step structure is fixed, not adaptive.** All 5 steps run
  for every company regardless of relevance -- e.g. a company with no
  near-term catalysts still gets a "catalysts/timeline" step. A more
  sophisticated planner would decide which sub-steps are worth running per
  company rather than always running a fixed template.
- **No cross-session memory or learning.** Each `thread_id` is fully
  independent; the system doesn't learn from a committee's history of
  approvals/rejections to calibrate future recommendations. This is
  actually consistent with the no-persistent-user-profile principle, but
  it does mean the system can't improve from feedback over time the way a
  real analyst team would.
- **A2A is in-process, not a networked deployment.** Fine for a
  single-process system; would need a real HTTP-based A2A layer if
  specialists were ever split across services or teams.
- **The `sentiment_sync` workaround is fragile to LangGraph upgrades.** It
  addresses a specific, reproduced bug in LangGraph 1.2.10's synchronization
  of asymmetric-depth parallel branches; a future LangGraph release might
  fix this at the framework level (making the barrier unnecessary) or
  change behavior in a way that needs a different workaround.
- **Industry/sector coverage is curated, not exhaustive.** Companies in an
  industry not listed in `data/industry_ratios.json` /
  `data/sector_indicators.json` fall back to sector-level or universal-only
  analysis, which is less precise than a bespoke ratio set.
- **`MAX_REVISION_ROUNDS` force-closes as rejected without diagnosing why**
  a revision cycle isn't converging -- a real committee workflow might want
  to know *what* kept failing to be addressed, not just that the cap was hit.
- **No automated evaluation harness.** Reasoning quality and recommendation
  consistency are currently checked only by manual testing and LangSmith
  trace inspection, not a repeatable, metric-based eval pipeline.

### Next steps

- Make the reasoning-step structure conditional (skip steps that don't
  apply, e.g. no catalysts identified) instead of always running all 5.
- Build a LangSmith-based automated evaluation (recommendation consistency
  across repeated runs, reasoning-step quality scoring) rather than relying
  on manual trace review.
- Move A2A to a real networked implementation if specialists ever need
  independent scaling or ownership.
- Expand industry/sector ratio coverage, or have an LLM propose a candidate
  ratio set for uncovered industries subject to human review, instead of a
  fixed sector-level default.
- Track *why* revision rounds fail to converge (e.g. surface a summary of
  unresolved feedback themes) instead of only enforcing a hard cap.
