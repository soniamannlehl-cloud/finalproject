# Investment Research Platform — Architecture

**Sonia Mannlehl** · UCLA Extension — Agentic AI & Autonomous Systems (Capstone)  
**Repository:** https://github.com/soniamannlehl-cloud/finalproject

> ⚠️ Academic capstone project. For educational purposes only. Not investment advice.

This document explains **how the platform is built**: the main parts, every agent, why I chose each framework, how data flows, and what I would improve. It is written to satisfy the course architecture and technical analysis requirements without reading like a corporate template.

---

# Part I — Architecture

## What I set out to build

Professional investors do not use one tool or one number. They use a **team** — people with different jobs who share findings, challenge each other, and only recommend action when the evidence supports it.

I built the same pattern with AI:

- A **planner** decides what to research (based on industry)
- **Specialist analysts** each own one slice of the work
- A **thesis** evolves as evidence arrives
- A **committee** argues bull and bear sides
- **You** confirm the company upfront and approve the report at the end

If evidence is too thin, the platform says **more research is needed** instead of guessing.

---

## The four main parts

The platform is not one big Python script. It is **four services** that talk over HTTP, plus a database.

```
┌─────────────────────────────────────────────────────────────┐
│  YOU  ──►  Web app (:3000)  ──►  API service (:8080)        │
│                                    │                        │
│                                    ├──► Specialists (:8081)  │
│                                    │         │              │
│                                    │         ▼              │
│                                    │    Yahoo · SEC · News  │
│                                    │                        │
│                                    ├──► Committee (:8082)    │
│                                    │      Bull · Bear · CIO │
│                                    │                        │
│                                    └──► PostgreSQL (:5432)  │
└─────────────────────────────────────────────────────────────┘
```

| Part | What it does |
|------|----------------|
| **Web app** | Where you start research and approve checkpoints |
| **API service** | Runs the workflow — planning, dispatch, thesis, safety, report |
| **Specialists service** | Ten research agents that fetch and analyze data |
| **Committee service** | Three agents that debate the investment case |
| **PostgreSQL** | Stores evidence, thesis history, and checkpoints |

**Three rules that keep the design clean:**

1. The **web app only talks to the API** — never directly to research agents.
2. The **API is the only part that writes to the database** — specialists return results; the API saves them.
3. The **API decides what to research** — specialists do not choose their own tasks.

---

## Diagram: every agent and how they work together

This is the main architecture diagram. It shows **all agents** in the order they run.

```
                              START
                                │
                                ▼
                   ┌────────────────────────┐
                   │ Company Validation     │  ← specialist agent
                   │ (resolve ticker)       │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  CHECKPOINT 1          │  ← you confirm the company
                   │  (human)               │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │ Research Planner       │  ← picks industry profile,
                   │                        │    builds research plan
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │ Research Director      │  ← assigns tasks to analysts
                   └───────────┬────────────┘
                               │
         ┌─────────────────────┼─────────────────────┐
         │                     │                     │
         ▼                     ▼                     ▼
   (parallel — only the agents the plan needs)

   Company Profile      Financial Analyst     Valuation Analyst
   Risk Analyst         Investment Driver     Competitor Analyst
   News Analyst         SEC Filings           Earnings Analyst

         │                     │                     │
         └─────────────────────┼─────────────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │ Evidence → PostgreSQL  │
                   │ Thesis Agent           │  ← thesis updates here
                   └───────────┬────────────┘
                               │
                    more tasks?├─── yes ──► back to Director
                               │
                               no
                               ▼
                   ┌────────────────────────┐
                   │ Safety checks          │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │ Investment Committee   │
                   │  Bull → Bear → CIO     │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │ Synthesizer            │  ← policy rules applied
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │ Report Generator       │
                   └───────────┬────────────┘
                               │
                               ▼
                   ┌────────────────────────┐
                   │  CHECKPOINT 2          │  ← you approve, reject,
                   │  (human)               │    or ask for more research
                   └───────────┬────────────┘
                               │
                               ▼
                             DONE
                    (replan loops back to Planner)
```

**Agent count:** 7 workflow agents in the API · 10 research specialists · 3 committee agents · 2 human checkpoints = **20 roles** in the full process.

Not every specialist runs on every company. A bank gets different metrics than a REIT — the Planner decides who to call.

---

## Agent roles (quick reference)

### Workflow agents (API service)

| Agent | Job |
|-------|-----|
| Research Planner | Build an industry-specific research plan |
| Research Director | Send tasks to specialists and track results |
| Thesis Agent | Keep the investment thesis updated as evidence arrives |
| Safety Pipeline | Check coverage, citations, stale data, contradictions |
| Synthesizer | Apply hard rules to the committee recommendation |
| Report Generator | Build the final HTML/PDF report |

### Research specialists (10 agents)

| Agent | Researches |
|-------|------------|
| Company Validation | Is this ticker valid and public? |
| Company Profile | Sector, industry, business description |
| Financial Analyst | Statements and ratios (math done in Python, not by the LLM) |
| Valuation Analyst | Peer-relative valuation |
| Risk Analyst | Industry-aware risk flags |
| Investment Driver | Key KPIs for this industry |
| Competitor Analyst | How the company ranks vs peers |
| News Analyst | Recent news tone and coverage |
| SEC Filings | Material EDGAR filings |
| Earnings Analyst | Beat/miss history |

### Investment committee (CrewAI)

| Agent | Job |
|-------|-----|
| Bull Analyst | Make the strongest case **for** investing |
| Bear Analyst | Make the strongest case **against** investing |
| CIO | Weigh both sides and propose buy / hold / sell / insufficient evidence |

The committee only sees a **short evidence brief** — it cannot go fetch new data or invent numbers that were not gathered.

---

## Why I used these frameworks

The course requires at least two agent frameworks. I used **three**, each for a job it is actually good at.

| Framework | Where | Why |
|-----------|-------|-----|
| **LangGraph + HITL** | API service | The workflow pauses twice for you to approve. LangGraph can interrupt, save state to Postgres, and resume when you click a button. |
| **A2A Protocol** | Specialists service | Research agents run as their own service. The Director discovers them at runtime instead of hard-coding imports. |
| **CrewAI** | Committee service | Bull/Bear/CIO role-play is what CrewAI is built for. The committee is short and self-contained — it does not need workflow checkpointing. |

**Google ADK — I looked at it, did not use it.** Specialist agents mostly fetch data and run Python calculations. They are not open-ended chat agents. Putting them in a heavy agent runtime would duplicate work the API already does.

---

## How data flows

Plain sequence — no jargon:

1. You enter a ticker in the web app.
2. The API validates the company (via the validation specialist).
3. You confirm at Checkpoint 1.
4. The Planner writes a research plan (tasks + dependencies, tailored to industry).
5. The Director sends tasks to specialists **in parallel batches**.
6. Each specialist calls external APIs, computes metrics, returns evidence.
7. The API saves evidence to Postgres and updates the thesis.
8. Steps 5–7 repeat until the plan is finished.
9. Safety checks run on all evidence.
10. The API sends a condensed brief to the committee; Bull, Bear, and CIO debate.
11. The Synthesizer applies policy rules (can block a buy/sell if evidence is weak).
12. The report is generated.
13. You review at Checkpoint 2 — approve, reject, or request more research.

**Data sources used:** Yahoo Finance, SEC EDGAR, FMP, NewsAPI, Tavily, Polygon/Massive. Only OpenAI is required; the rest have fallbacks or graceful degradation.

**Where things live:**

| In memory / workflow state | In PostgreSQL |
|----------------------------|---------------|
| Current plan, task status | Evidence payloads |
| Evidence ID lists | Claims, thesis versions |
| Checkpoint decisions | Reports |

---

## Key design decisions

| I chose… | Because… | Tradeoff |
|----------|----------|----------|
| Separate services | Real agent boundaries; committee failures do not crash the workflow | More moving parts in Docker |
| A research **plan** before execution | Banks and REITs need different analysis — visible and testable | Not a one-size-fits-all pipeline |
| Python for financial math | LLMs make arithmetic mistakes | Less “magic” at the data layer |
| Policy rules after the committee | A confident LLM debate should not override weak evidence | Can block flashy but unsupported calls |
| Capped retries and replans | Prevents runaway cost and infinite loops | Sometimes stops before “perfect” |

---

# Part II — Technical Analysis

## Planning: how the platform decides what to do

I use **three planning styles**, depending on how predictable the work is:

**Specialist agents — fixed steps, not ReAct.**  
Each analyst follows the same path every time: get data → clean it → compute → optionally interpret. I did not give them a free-form “pick any tool” loop because the steps are already known, and a free agent might skip SEC filings or stop early.

**The Planner — explicit task breakdown.**  
Before any research runs, the Planner outputs a structured plan: which capabilities to call, in what order, with what industry metrics. That plan shows up in the UI. This is **hierarchical decomposition** — break the big job into smaller jobs with dependencies.

**Checkpoint 2 — replan when you ask for more.**  
If you request additional analysis, the Planner writes a new plan version. The Director only re-runs tasks that were not already done. This is **monitor-and-revise** — fix the plan, do not just patch the report text.

**What I did not do:** a single ReAct agent doing everything (too messy, hard to cite evidence), or a fixed pipeline identical for every industry (wrong metrics for banks vs tech).

---

## Coordination: how agents work together

The main pattern is **orchestrator + workers**:

- **LangGraph** (orchestrator) owns the step-by-step workflow.
- **Director** (worker dispatcher) sends jobs to specialists via A2A.
- **Committee** is a separate worker called once research is done.

```
        LangGraph orchestrator
               │
     ┌─────────┼─────────┐
     ▼         ▼         ▼
 Financial  Valuation   Risk  …  (specialists)
     │         │         │
     └─────────┴─────────┘
               │
               ▼
         Bull / Bear / CIO
               │
               ▼
         back to orchestrator
```

**Compared to alternatives:**

| Approach | My take |
|----------|---------|
| **Orchestrator + workers** (what I built) | Research steps have known order (valuation needs financials first). Easy to debug. |
| **Group chat** (e.g. AutoGen agents talking to each other) | Would hide that structure. Hard to retry one failed step. |
| **Shared blackboard** (agents grab work from a pool) | Evidence store is shared, but the Director explicitly assigns tasks — not a free-for-all. |

Specialists **never call each other**. If valuation needs financials, that dependency is in the plan — not a side conversation between agents.

---

## Limitations (honest)

| Limitation | What it means in practice |
|------------|---------------------------|
| 13 industry profiles | Unknown industries get a generic plan — less tailored metrics |
| No learning across runs | Each research run starts fresh |
| Runs locally in Docker | Reviewers need to run it themselves or watch a screen recording |
| Committee uses real LLM calls | Most expensive part of each run |
| Semantic safety checks use an LLM | Can miss things; deterministic checks are the real safety net |
| No hard token budget per run | Retries are capped, but total spend is not |

**What I would add next:** hosted demo URL, more industry profiles, per-run cost caps, and publishing the shared contracts package so others can reuse the schemas.

---

## Course frameworks (summary)

| Framework | Used? |
|-----------|-------|
| LangGraph + HITL | ✅ |
| A2A Protocol | ✅ |
| CrewAI | ✅ |
| Google ADK | ❌ evaluated, not used |
| n8n | ❌ not needed |

---

*Related docs: [README.md](README.md) (how to run it) · [docs/AGENTS.md](docs/AGENTS.md) (agent file paths)*
