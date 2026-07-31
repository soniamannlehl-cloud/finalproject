# Architecture

## Overview

The Collaborative Investment Research Platform is a multi-agent LangGraph
system that researches a publicly traded company across three dimensions
(sentiment, financials, macro/industry) and synthesizes the findings into a
beginner-friendly memo -- without ever issuing a buy/sell/hold
recommendation. Two human-in-the-loop checkpoints keep the user in control:
confirming the company before research starts, and reviewing (with
open-ended Q&A) before the session closes on the user's own conclusion.

## System diagram

```mermaid
flowchart TD
    START([user input]) --> Intake[Intake & Validation Agent]
    Intake -- "no match / rejected" --> ENDTURN([turn ends -- retry next message])
    Intake -- "Checkpoint #1: confirm Y/N" -.->|interrupt| Intake

    Intake -- confirmed --> Sentiment[Sentiment Analyst]
    Intake -- confirmed --> Financial[Financial Analyst]
    Intake -- confirmed --> Macro[Macro & Industry Analyst]

    Sentiment --> DataCheck{Data Failure Check}
    Financial --> DataCheck
    Macro --> DataCheck

    DataCheck -- "1-2 failed: pass through" --> BuildMemo[Orchestrator: build memo]
    DataCheck -- "3/3 failed" -.->|interrupt: total failure| DataCheck
    DataCheck -- "retry" --> Sentiment

    BuildMemo --> Checkpoint2[Checkpoint #2: memo review + Q&A]
    Checkpoint2 -- "question" -->|A2A route_question| Specialist[owning specialist's answer_question]
    Specialist --> Checkpoint2
    Checkpoint2 -- "close + takeaway" --> END([complete])
```

Financial Analyst and Macro & Industry Analyst each resolve `industry`/
`sector` themselves at the start of their own execution (a cheap,
already-fetched yfinance lookup) rather than depending on a separate
"Industry Identification" graph node. See **Engineering tradeoffs** below
for why.

## Node walkthrough

| Node | Type | Notes |
|---|---|---|
| `intake_validation` | LLM agent | Ticker/company search, LLM extraction pre-step for freeform phrasing ("the Delta situation"), LLM classification (private vs. not-found) when no match is found. Owns Checkpoint #1. |
| `sentiment_analyst` | LLM agent | News search (`scope="company"`), flags low-coverage deterministically. |
| `financial_analyst` | LLM agent + deterministic math | yfinance primary / Alpha Vantage fallback for raw data; ratios computed by `tools/financial_calculations.py` (never by the LLM); LLM only interprets the results. Flags stale/incomplete filings. |
| `macro_industry_analyst` | LLM agent + deterministic math | FRED indicators + trend, sector ETF performance vs. S&P 500 (`tools/macro_calculations.py`), industry-specific indicators from `data/sector_indicators.json`, qualitative industry landscape via news search. |
| `data_failure_check` | Deterministic | The only data-related interrupt: hard-stops and offers retry only when all 3 specialists fail. |
| `build_memo` | LLM agent (Orchestrator) | 4 separate LLM calls for the explicit reasoning chain (evidence pattern -> risk factors -> invalidation triggers -> catalysts/timeline), each independently inspectable in LangSmith traces, followed by one synthesis call for the beginner-friendly memo. |
| `checkpoint_2_review` | LLM agent (Orchestrator) | Loops on `interrupt()` for open-ended Q&A, routes each question via the A2A router, closes on the user's free-form takeaway. |

## Framework justification

### LangGraph with HITL

LangGraph's `interrupt()` / `Command(resume=...)` pattern is the backbone.
It was chosen because the product requirement is fundamentally about
*pausing exactly where a human decision belongs* -- confirming a company
match, and reviewing a memo before closing -- without losing the state
already gathered (specialist outputs, reasoning chain, Q&A history). A
SQLite checkpointer persists this state across turns, so a multi-message
conversation (confirm -> research -> review -> ask questions -> close) is
really one checkpointed graph run resumed repeatedly.

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
  system needs twice (Checkpoint #1 and the multi-turn Checkpoint #2 Q&A
  loop). Bolting that on would mean reimplementing what LangGraph already
  provides.
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
   match, not just ambiguous ones, per the brief. "No" or no-match loops
   back to a fresh `intake_validation` attempt; because there's no
   frontend in this build, "loop back" is implemented as ending that graph
   turn and letting the next `invoke()` call (same `thread_id`) start a new
   attempt, rather than nesting a second `interrupt()` inside the same
   node call.
2. **Checkpoint #2 (Memo Review + Q&A)** -- one node loops on `interrupt()`
   as many times as the user has questions, each one dispatched via A2A to
   the owning specialist and appended to `checkpoint_2_qa_history`. It
   closes only on the user's own free-form `user_takeaway` -- there is no
   approve/reject verdict anywhere in this flow, matching the
   non-negotiable principle that the system never issues a recommendation.
3. **Total data failure** -- the only data-related interrupt; 1 or 2
   specialist failures pass through silently to the Orchestrator, which
   discloses the gap in the memo (`data_gaps`) instead of interrupting the
   user over a partial result.

## Non-negotiable principles, enforced in code (not just prompted)

- **No buy/sell/hold verdicts**: enforced via system-prompt instructions
  at every LLM call site in the Orchestrator, plus the evidence-pattern
  classification being explicitly framed as descriptive ("fits a
  growth-style profile"), never advice.
- **Deterministic math, never LLM arithmetic**: every ratio and trend has
  its own guarded Python function (`tools/financial_calculations.py`,
  `tools/macro_calculations.py`); the LLM only ever receives
  already-computed values to interpret.
- **No persistent user profile**: nothing about the user (risk tolerance,
  goals) is stored anywhere in `state.py` or the checkpointer -- only the
  research and the user's own free-form takeaway for that session.
- **Transparent failure disclosure**: low sentiment coverage, stale/
  incomplete filings, and partial specialist failures are flagged with a
  deterministic prefix in the relevant text field (not left to the LLM's
  discretion to remember to mention).
- **A2A-routed Q&A**: every Checkpoint #2 question is dispatched to a
  specific specialist's `answer_question()`, never answered generically by
  the Orchestrator.

## Engineering tradeoffs

- **Flat specialist fan-out instead of a diamond.** The brief describes
  Industry Identification as a deterministic step running in parallel with
  Sentiment Analyst, with Financial and Macro & Industry Analyst depending
  on its output. Implemented literally, this creates an asymmetric-depth
  diamond (Sentiment: 1 hop from the fan-out; Financial/Macro: 2 hops via
  Industry Identification) that converges before `data_failure_check` and,
  further downstream, the multi-turn `interrupt()` loop in Checkpoint #2.
  This exact shape reproducibly corrupted execution in LangGraph 1.2.10 on
  resume (verified via isolated minimal repros: a flat 3-way fan-out works
  cleanly; the diamond causes either an `InvalidUpdateError` on the
  `status` channel or, with a permissive reducer, a spurious duplicate
  interrupt). The fix was to remove the diamond: Financial Analyst and
  Macro & Industry Analyst each resolve `industry`/`sector` inline (a
  cheap, already-fetched yfinance `.info` lookup) instead of depending on
  a shared upstream node, so all 3 specialists fan out flatly and
  simultaneously.
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
