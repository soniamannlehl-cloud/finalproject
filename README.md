# AI Investment Research Analyst

A multi-agent system that simulates how a professional investment research
firm performs due diligence on a publicly traded company: it plans a
research strategy, dispatches specialist agents to gather evidence, maintains
a living investment thesis, subjects its conclusions to safety review, runs
an adversarial investment committee, and requires human approval before any
recommendation is finalized.

The emphasis is architecture, planning, explainability, and engineering
discipline — not generating investment advice. Every factual statement in
the output is traceable to a specific piece of retrieved evidence, and the
system refuses to issue a directional call when evidence is insufficient.

> ⚠️ Academic project. Not investment advice.

---

## Architecture at a glance

Three Python services with **mutually incompatible dependency trees**, split
deliberately so each framework can be used where it is genuinely best:

| Service | Port | Framework | Role |
|---|---|---|---|
| `api` | 8080 | **LangGraph** | Control plane — workflow, HITL, planning, safety |
| `specialists` | 8081 | **A2A** | Data plane — research agents + provider APIs |
| `committee` | 8082 | **CrewAI** | Deliberation — Bull / Bear / CIO debate |
| `postgres` | 5432 | — | Evidence repository + workflow checkpoints |

The split is not decoration: LangGraph and CrewAI pin conflicting
`langchain-core` ranges and cannot share a Python environment. Isolating them
behind **A2A** is what makes using both viable, and it is what makes A2A
load-bearing rather than ceremonial. See
[ARCHITECTURE.md](ARCHITECTURE.md) for the full rationale and the
counter-experiment that verifies it.

```
  Next.js frontend
        │
        ▼
  ┌───────────────┐   A2A/HTTP   ┌──────────────────┐
  │ api           │─────────────▶│ specialists      │──▶ FMP · yfinance
  │ (LangGraph)   │              │ (A2A + tools)    │    SEC · NewsAPI
  │ control plane │              │ data plane       │    Tavily · Polygon
  └───────┬───────┘              └──────────────────┘
          │ A2A/HTTP             ┌──────────────────┐
          ├─────────────────────▶│ committee        │
          │                      │ (CrewAI)         │
          │                      └──────────────────┘
          ▼
     Postgres  ◀── evidence, thesis history, checkpoints
```

---

## Quick start

**Prerequisites:** Docker Desktop, and an OpenAI API key.

```bash
cp .env.example .env
```

Add your `OPENAI_API_KEY` to `.env`, then:

```bash
docker compose up --build
```

Verify all three services are healthy:

```bash
curl http://localhost:8080/health && curl http://localhost:8081/health && curl http://localhost:8082/health
```

| URL | What it is |
|---|---|
| http://localhost:8080/docs | API service — interactive OpenAPI docs |
| http://localhost:8081/agents | Specialist fleet discovery (A2A) |
| http://localhost:8082/health | Committee service health |

### API keys

Only `OPENAI_API_KEY` is required. Every data provider has a keyless
fallback (yfinance), so the platform runs and demonstrates gracefully with
no paid data subscriptions — missing providers reduce the evidence score
and are **disclosed in the report** rather than silently ignored.

| Key | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | **Yes** | All agent reasoning |
| `LANGSMITH_API_KEY` | Recommended | Traces every agent decision |
| `FMP_API_KEY` | Optional | Financial statements (falls back to yfinance) |
| `NEWSAPI_KEY` | Optional | News (falls back to Tavily) |
| `TAVILY_API_KEY` | Optional | Web search fallback |
| `POLYGON_API_KEY` | Optional | Market data fallback |

---

## Repository layout

```
├── packages/contracts/     Shared Pydantic schemas — the seam between services.
│                           Pydantic-only by design; adding a framework here
│                           would reintroduce the conflict the split prevents.
├── services/
│   ├── api/                LangGraph workflow, HITL, planning, safety, reports
│   ├── specialists/        Research agents, data-provider tools, A2A server
│   └── committee/          CrewAI Bull / Bear / CIO
├── frontend/               Next.js + React + Tailwind
├── ops/db/init/            Postgres schema
└── docs/                   Diagrams, ADRs, sample reports
```

---

## Development

Run the contracts test suite (no Docker required):

```bash
python -m venv .venv-contracts && .venv-contracts/Scripts/pip install -e packages/contracts pytest
```

```bash
.venv-contracts/Scripts/python -m pytest packages/contracts/tests -v
```

---

## Build status

Built incrementally; each milestone ends compiling, tested, and committed.

| Milestone | Scope | Status |
|---|---|---|
| **M0** | Service skeletons, contracts, Docker, dependency isolation proof | ✅ |
| M1 | Company validation + HITL #1 + checkpointing | ⬜ |
| M2 | Planner → Director → one specialist over real A2A (vertical slice) | ⬜ |
| M3 | Full specialist fleet + parallel fan-out + retry/fallback | ⬜ |
| M4 | Evidence repository + versioned living thesis | ⬜ |
| M5 | Safety pipeline + `INSUFFICIENT_EVIDENCE` path | ⬜ |
| M6 | CrewAI investment committee | ⬜ |
| M7 | HITL #2 + replan loop | ⬜ |
| M8 | PDF report generation | ⬜ |
| M9 | Frontend | ⬜ |
| M10 | LangSmith cross-service tracing + evaluation harness | ⬜ |

---

## Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — system design, framework
  justification, data flow, tradeoffs, and technical analysis.
