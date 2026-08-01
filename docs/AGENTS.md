# Agents Reference

Where every agent lives, what it does, and how they connect.

The platform has **three layers** of agents:

| Layer | Service | Folder | Role |
|-------|---------|--------|------|
| **Research specialists** | `specialists` (:8081) | `services/specialists/app/agents/` | Fetch data, compute metrics, return evidence |
| **Workflow orchestration** | `api` (:8080) | `services/api/app/` | Plan, dispatch, thesis, safety, report, HITL |
| **Investment committee** | `committee` (:8082) | `services/committee/app/crew/` | Bull / Bear / CIO debate |

The **registry** that maps capabilities → code is here:

```
services/specialists/app/a2a/cards.py
```

---

## Workflow (how agents run in order)

```
validate_company → planner → director ⇄ specialists → collect → thesis
  → safety → committee → synthesizer → report → HITL #2
```

Defined in: `services/api/app/graph/builder.py`

---

## 1. Research specialist agents (10 agents, 11 capabilities)

These run in the **specialists service**. Each file in `services/specialists/app/agents/` is one agent.

| Agent | File | Capability | What it does |
|-------|------|------------|--------------|
| **Company Validation** | `company_validation.py` | `company.validate` | Resolves ticker/name to a public company; flags private or unknown |
| **Company Profile** | `company_profile.py` | `company.profile` | Sector, industry, business description, market cap |
| **Financial Analyst** | `financial_analyst.py` | `financials.statements` | Raw income statement, balance sheet, cash flow from Yahoo Finance |
| **Financial Analyst** | `financial_analyst.py` | `financials.ratios` | Industry-profile metrics (computed in Python, LLM interprets only) |
| **Valuation Analyst** | `valuation_analyst.py` | `valuation.estimate` | Peer-relative valuation using profile's methods (P/E, EV/EBITDA, P/B, etc.) |
| **Risk Analyst** | `risk_analyst.py` | `risk.analysis` | Threshold-based risks from profile rules + industry risk context |
| **Investment Driver** | `investment_driver_agent.py` | `investment.drivers` | Assesses profile KPIs and investment drivers vs computed metrics |
| **Competitor Analyst** | `competitor_analyst.py` | `competitors.analysis` | Percentile rank vs industry peers on profile competitive factors |
| **News Analyst** | `news_analyst.py` | `news.sentiment` | Recent news coverage and sentiment tone |
| **SEC Filings** | `sec_filings.py` | `filings.sec` | Material SEC filings from EDGAR |
| **Earnings Analyst** | `earnings_analyst.py` | `earnings.call` | Earnings history, beat/miss track record, next report date |

### Supporting tools (not agents — used by agents above)

```
services/specialists/app/tools/
├── yfinance_tool.py          market data & financial statements
├── financial_calculations.py deterministic metrics (never LLM math)
├── peers_tool.py             industry peer lookup & multiples
├── fmp_tool.py               Financial Modeling Prep API
├── sec_edgar.py              SEC EDGAR filings
├── news_tool.py              news search
└── polygon_tool.py             Polygon market data
```

### How to add a new specialist agent

1. Create `services/specialists/app/agents/my_agent.py` with `AGENT_ID` and `handle()` function
2. Register in `services/specialists/app/a2a/cards.py` → `CAPABILITY_HANDLERS` and `AGENT_CAPABILITIES`
3. Add capability to `packages/contracts/src/contracts/enums.py` → `Capability`
4. Add to industry profile(s) in `packages/contracts/src/contracts/industry_profiles/profiles.py`

---

## 2. Control-plane agents (API service)

These live in the **api service** and orchestrate the workflow. They do not call data providers directly.

| Agent / Node | File | What it does |
|--------------|------|--------------|
| **Company Validation (HITL #1)** | `graph/nodes/validate.py` | Confirms company with user; sets sector/industry |
| **Research Planner** | `planning/planner.py` | Selects industry profile, builds task DAG |
| **Research Director** | `director/director.py` | Dispatches tasks to specialists via A2A in parallel layers |
| **Specialist Proxy** | `director/director.py` | HTTP bridge to specialists service per task |
| **Thesis Agent** | `thesis/agent.py` | Living investment thesis; updates after each evidence batch |
| **Thesis Framework** | `thesis/framework.py` | Builds structured analyst thesis (core question, drivers, risks, etc.) |
| **Safety Pipeline** | `safety/pipeline.py` | Evidence verification, coverage checks, contradiction detection |
| **Synthesizer** | `graph/nodes/synthesizer.py` | Applies deterministic policy gate to committee recommendation |
| **Report Generator** | `graph/nodes/report.py` + `report/generator.py` | Assembles HTML/PDF investment report |
| **HITL #2** | `graph/nodes/hitl_2.py` | Human reviews report + recommendation before finalize |

### Industry profiles (config, not an agent)

The Planner reads these **before** any specialist runs:

```
packages/contracts/src/contracts/industry_profiles/
├── profile.py      IndustryProfile schema
├── profiles.py     Technology, Banking, Insurance, Healthcare, …
└── registry.py     classify() + get_profile()
```

---

## 3. Investment committee agents (CrewAI)

These run in the **committee service** — adversarial debate, not data retrieval.

| Agent | File | What it does |
|-------|------|--------------|
| **Bull Analyst** | `crew/committee.py` | Strongest evidence-based case FOR owning the company |
| **Bear Analyst** | `crew/committee.py` | Strongest evidence-based case AGAINST |
| **CIO** | `crew/committee.py` | Weighs both sides; outputs buy/hold/sell + confidence |

Brief builder (feeds the committee): `services/api/app/committee/brief_builder.py`  
Committee client (API → committee): `services/api/app/committee/client.py`  
Committee node (LangGraph): `services/api/app/graph/nodes/committee.py`

---

## Quick file tree

```
services/
├── specialists/                    ← DATA PLANE (specialist agents)
│   └── app/
│       ├── agents/                 ← ★ ONE FILE PER AGENT (start here)
│       │   ├── company_validation.py
│       │   ├── company_profile.py
│       │   ├── financial_analyst.py
│       │   ├── valuation_analyst.py
│       │   ├── risk_analyst.py
│       │   ├── investment_driver_agent.py
│       │   ├── competitor_analyst.py
│       │   ├── news_analyst.py
│       │   ├── sec_filings.py
│       │   └── earnings_analyst.py
│       ├── a2a/
│       │   └── cards.py            ← ★ REGISTRY: capability → handler
│       └── tools/                  ← shared data/compute helpers
│
├── api/                            ← CONTROL PLANE (orchestration)
│   └── app/
│       ├── planning/planner.py     ← Research Planner
│       ├── director/director.py    ← Research Director
│       ├── thesis/agent.py         ← Living thesis
│       ├── safety/pipeline.py      ← Safety gate
│       ├── report/generator.py     ← Report assembly
│       └── graph/
│           ├── builder.py          ← ★ WORKFLOW TOPOLOGY
│           └── nodes/              ← validate, committee, synthesizer, report, hitl_2
│
└── committee/                      ← DELIBERATION PLANE
    └── app/crew/
        ├── committee.py            ← ★ Bull, Bear, CIO (CrewAI)
        └── brief.py                ← Evidence brief for committee
```

---

## Capability enum (shared vocabulary)

All capability strings are defined in:

```
packages/contracts/src/contracts/enums.py  →  class Capability
```

Current capabilities:

- `company.validate`
- `company.profile`
- `financials.statements`
- `financials.ratios`
- `valuation.estimate`
- `risk.analysis`
- `investment.drivers`
- `competitors.analysis`
- `news.sentiment`
- `filings.sec`
- `earnings.call`

---

## See also

- [ARCHITECTURE.md](../ARCHITECTURE.md) — full system design
- [docs/RUBRIC_ALIGNMENT.md](RUBRIC_ALIGNMENT.md) — course requirements mapping
