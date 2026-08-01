# Project structure

How this repository is organized, where to find things, and why it is split this way.

---

## Start here

| If you want… | Open this |
|--------------|-----------|
| Run the app | [README.md](../README.md) |
| List of every agent + code file | [AGENTS.md](AGENTS.md) |
| System design & frameworks | [ARCHITECTURE.md](../ARCHITECTURE.md) |
| Guardrails & validation | [GUARDRAILS.md](GUARDRAILS.md) |

---

## Mental model (3 planes)

The project is **not** one folder of agents. It is three cooperating services plus shared contracts:

```
┌─────────────────────────────────────────────────────────────┐
│  frontend/          Web UI (Next.js)                        │
└───────────────────────────┬─────────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────────┐
│  services/api/        ORCHESTRATION (LangGraph workflow)     │
│    • Plans research                                         │
│    • Dispatches work                                        │
│    • Thesis, safety, report, human checkpoints              │
└───────┬───────────────────────────────┬───────────────────┘
        │ A2A                             │ A2A
┌───────▼──────────────┐         ┌────────▼──────────────────┐
│ services/specialists/│         │ services/committee/       │
│ RESEARCH AGENTS      │         │ COMMITTEE AGENTS          │
│ (data & analysis)    │         │ (Bull / Bear / CIO)       │
└──────────────────────┘         └───────────────────────────┘
        │                                   │
        └───────────────┬───────────────────┘
                        ▼
              packages/contracts/     Shared schemas (all services)
              ops/db/                   Postgres schema
```

**Rule of thumb**

- **Need agent code that calls Yahoo, SEC, news APIs?** → `services/specialists/app/agents/`
- **Need workflow / planner / thesis / report?** → `services/api/app/`
- **Need Bull/Bear/CIO debate?** → `services/committee/app/crew/`
- **Need shared types (Evidence, Plan, Thesis)?** → `packages/contracts/`

---

## Top-level folders

```
finalproject/
├── README.md                 Setup & quick start
├── ARCHITECTURE.md           Full system design (submission artifact)
├── docker-compose.yml        Starts all services
├── .env.example              API keys template
│
├── docs/                     Human-readable guides
│   ├── AGENTS.md             ★ Every agent + file path
│   ├── PROJECT_STRUCTURE.md  ★ This file
│   ├── GUARDRAILS.md         Validation & error-handling reference
│   └── DEMO_SCRIPT.md
│
├── packages/
│   └── contracts/            ★ Shared Pydantic models (no framework deps)
│       └── src/contracts/
│           ├── enums.py          Capabilities, industry classifications, actions
│           ├── evidence.py       Evidence & claims
│           ├── plan.py           ResearchPlan & tasks
│           ├── thesis.py         Thesis & structured framework
│           └── industry_profiles/  ★ Industry research configs
│
├── services/
│   ├── api/                  ★ Control plane (orchestrator)
│   ├── specialists/          ★ Research agents (data plane)
│   └── committee/            Committee agents (CrewAI)
│
├── frontend/                 Next.js dashboard
├── ops/db/init/              SQL schema for Postgres
├── evaluation/               Consistency / eval scripts
└── scripts/                  Utility scripts
```

---

## Service internals

### `services/specialists/` — research agents

```
specialists/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py               FastAPI entry
    ├── a2a/
    │   ├── cards.py          ★ REGISTRY: capability → agent handler
    │   └── server.py         A2A protocol endpoint
    ├── agents/               ★ ONE PYTHON FILE PER AGENT
    │   ├── company_validation.py
    │   ├── company_profile.py
    │   ├── financial_analyst.py
    │   ├── valuation_analyst.py
    │   ├── risk_analyst.py
    │   ├── investment_driver_agent.py
    │   ├── competitor_analyst.py
    │   ├── news_analyst.py
    │   ├── sec_filings.py
    │   └── earnings_analyst.py
    └── tools/                Data helpers (not agents)
        ├── yfinance_tool.py
        ├── financial_calculations.py
        └── peers_tool.py
```

### `services/api/` — orchestration

```
api/
├── Dockerfile
├── requirements.txt
├── tests/                    API unit tests
└── app/
    ├── main.py               FastAPI entry
    ├── api/routes.py         REST endpoints for frontend
    ├── config.py
    │
    ├── graph/                ★ LangGraph workflow
    │   ├── builder.py        Workflow topology (read this first)
    │   ├── state.py          Shared run state
    │   └── nodes/            One file per workflow step
    │       ├── validate.py       HITL #1 — confirm company
    │       ├── committee.py      Call committee service
    │       ├── synthesizer.py    Policy gate
    │       ├── report.py         Generate report
    │       └── hitl_2.py         HITL #2 — approve recommendation
    │
    ├── planning/             Research strategy
    │   └── planner.py        ★ Planner agent
    │
    ├── director/             Task dispatch
    │   ├── director.py       ★ Director — sends work to specialists
    │   └── a2a_client.py     HTTP to specialists service
    │
    ├── thesis/               Living investment thesis
    │   ├── agent.py          ★ Thesis agent (LangGraph node)
    │   ├── framework.py      Structured analyst thesis
    │   └── signals.py        Evidence → bull/bear signals
    │
    ├── safety/               Evidence verification
    │   └── pipeline.py       ★ Safety pipeline
    │
    ├── report/               Report generation
    │   ├── generator.py
    │   ├── formatters.py
    │   └── templates/
    │
    ├── committee/            Client for committee service
    │   ├── client.py
    │   └── brief_builder.py
    │
    ├── evidence/             DB access for evidence
    └── db/                   Postgres checkpointer
```

### `services/committee/` — investment committee

```
committee/
├── Dockerfile
├── requirements.txt
└── app/
    ├── main.py
    └── crew/
        ├── committee.py      ★ Bull, Bear, CIO (CrewAI)
        └── brief.py          Evidence brief builder
```

### `packages/contracts/` — shared vocabulary

Everything both services agree on. **No LangGraph, CrewAI, or FastAPI imports here.**

Industry profiles (Technology, Banking, REIT, …) live here so both Planner and specialists use the same config:

```
contracts/src/contracts/industry_profiles/
├── profile.py      Schema
├── profiles.py     All industry definitions
└── registry.py     classify() + get_profile()
```

---

## Why not one `agents/` folder?

Three separate Python environments are required:

| Service | Framework | Why separate |
|---------|-----------|--------------|
| api | LangGraph | Workflow, checkpoints, HITL |
| specialists | A2A SDK | Agent discovery & task protocol |
| committee | CrewAI | Role-based adversarial debate |

Putting all agents in one folder would force one `requirements.txt` and break at least one framework. The split is intentional; `packages/contracts` is the shared seam.

---

## Optional future cleanup (not done yet)

These would improve clarity but require path updates in Docker, imports, and tests:

| Change | Benefit | Cost |
|--------|---------|------|
| Rename `services/` → `apps/` | Matches common monorepo convention | Update docker-compose, docs |
| Group `specialists/app/agents/` into subfolders (`financial/`, `market/`) | Easier browsing | Update `cards.py` imports |
| Move `ARCHITECTURE.md` → `docs/` | Cleaner root | Rubric expects it at root |
| Single `tests/` at repo root | One place for all tests | Restructure CI |

For the capstone demo, **navigation docs + service READMEs** give most of the benefit without migration risk.

---

## Local dev clutter

You may see `.venv-api`, `.venv-specialists`, etc. at the repo root — these are local Python virtualenvs (gitignored). They are not part of the architecture; Docker is the supported run path.
