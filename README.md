# AI Investment Research Analyst

A multi-agent system that simulates how a professional investment research
firm performs due diligence on a publicly traded company: it plans an
industry-aware research strategy, dispatches specialist agents to gather
evidence, maintains a living investment thesis, subjects its conclusions to
safety review, runs an adversarial investment committee, generates a
structured report, and requires human approval before any recommendation is
finalized.

The emphasis is architecture, planning, explainability, and engineering
discipline — not generating investment advice. Every factual statement in
the output is traceable to a specific piece of retrieved evidence, and the
system refuses to issue a directional call when evidence is insufficient.

> ⚠️ Academic project. Not investment advice.

---

## What this system does

| Feature | Description |
|---|---|
| **Web dashboard** | Next.js UI at `:3000` — start runs, approve checkpoints, view evidence, thesis, safety, and reports |
| **Industry-aware planning** | 13 industry profiles (Technology, Banking, REIT, Healthcare, …) select metrics, valuation methods, and risk rules per company |
| **10 research specialists** | 11 capabilities over A2A — financials, valuation, risk, peers, news, SEC, earnings, investment drivers |
| **Living thesis** | Versioned stance + structured analyst framework (core question, drivers, risks, catalysts, valuation view) |
| **Safety pipeline** | Deterministic coverage/citation checks + semantic hallucination/contradiction detection |
| **Investment committee** | CrewAI Bull / Bear / CIO debate from a capped evidence brief only |
| **Policy gate** | Deterministic synthesizer overrides committee when evidence is insufficient |
| **Two HITL checkpoints** | Confirm company before spend; review full report before finalize (with replan option) |
| **Guardrails** | Bounded retries/replans, run-scoped evidence IDs, LLM never computes financial numbers |

**End-to-end workflow:**

```
validate → planner → director ⇄ specialists → collect → thesis → safety
  → committee → synthesizer → report → HITL #2
```

---

## Architecture at a glance

Four runtime components plus shared contracts:

| Component | Port | Framework | Role |
|---|---|---|---|
| `frontend` | 3000 | **Next.js** | Web UI — research dashboard and HITL checkpoints |
| `api` | 8080 | **LangGraph** | Control plane — workflow, HITL, planning, safety, reports |
| `specialists` | 8081 | **A2A** | Data plane — 10 research agents + provider APIs |
| `committee` | 8082 | **CrewAI** | Deliberation — Bull / Bear / CIO debate |
| `postgres` | 5432 | — | Evidence repository + workflow checkpoints |

Three Python services share **no dependency tree** — they communicate only
through HTTP and the shared `packages/contracts` Pydantic schemas. A2A is a
real network protocol: specialists are separately addressable and discovered
at runtime.

See [ARCHITECTURE.md](ARCHITECTURE.md) for framework justification, data
flow, and measured tradeoffs.

```
  Next.js frontend (:3000)
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

**Prerequisites:** Docker Desktop and an OpenAI API key.

```bash
cp .env.example .env
# Edit .env and set OPENAI_API_KEY

docker compose up --build
```

Wait until all containers are healthy, then open the UI:

| URL | What it is |
|---|---|
| **http://localhost:3000** | **Web UI** — start research and approve recommendations |
| http://localhost:8080/docs | API — interactive OpenAPI docs |
| http://localhost:8081/agents | Specialist fleet discovery (A2A) |
| http://localhost:8082/health | Committee service health |

Verify services:

```bash
docker compose ps
curl http://localhost:8080/health
```

**Try a run:** open http://localhost:3000 → enter a ticker (e.g. `NVDA`) →
confirm at Checkpoint #1 → watch evidence and thesis update → review the
report at Checkpoint #2.

### API keys

Only `OPENAI_API_KEY` is required. Every data provider has a keyless
fallback (yfinance), so the platform runs gracefully without paid data
subscriptions — missing providers reduce the evidence score and are
**disclosed in the report** rather than silently ignored.

| Key | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | **Yes** | All agent reasoning |
| `LANGSMITH_API_KEY` | Recommended | Traces every agent decision |
| `FMP_API_KEY` | Optional | Financial statements (falls back to yfinance) |
| `NEWSAPI_KEY` | Optional | News (falls back to Tavily) |
| `TAVILY_API_KEY` | Optional | Web search fallback |
| `POLYGON_API_KEY` | Optional | Market quotes via Massive (formerly Polygon.io) |

---

## Repository layout

```
├── packages/contracts/     Shared Pydantic schemas — the seam between services
│                           industry_profiles/ (Technology, Banking, REIT, …)
├── services/
│   ├── api/                LangGraph workflow, HITL, planning, safety, reports
│   ├── specialists/        ★ Research agents → specialists/app/agents/
│   └── committee/          CrewAI Bull / Bear / CIO
├── frontend/               Next.js + React + Tailwind dashboard
├── ops/db/init/            Postgres schema
├── evaluation/             Consistency harness (optional)
└── docs/                   Guides — start with PROJECT_STRUCTURE.md & AGENTS.md
```

**Where to look:**

| Need | Path |
|---|---|
| Research agents (10) | `services/specialists/app/agents/` |
| Capability registry | `services/specialists/app/a2a/cards.py` |
| Workflow topology | `services/api/app/graph/builder.py` |
| Industry profiles | `packages/contracts/src/contracts/industry_profiles/` |
| Committee debate | `services/committee/app/crew/` |
| Frontend UI | `frontend/src/` |

See **[docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)** for a full
folder map and **[docs/AGENTS.md](docs/AGENTS.md)** for every agent and
what it does.

---

## Development

Run the contracts test suite (no Docker required):

```bash
python -m venv .venv-contracts
.venv-contracts/Scripts/pip install -e packages/contracts pytest   # Windows
.venv-contracts/Scripts/python -m pytest packages/contracts/tests -v
```

Run API unit tests (requires `pip install -e packages/contracts` and
service dependencies in your venv):

```bash
cd services/api
pip install -r requirements.txt
python -m pytest tests/test_planning.py tests/test_thesis_framework.py tests/test_safety.py -v
```

Run the evaluation harness (API must be running):

```bash
pip install httpx
python evaluation/run_consistency.py --ticker NVDA --runs 2
```

---

## Documentation

| Doc | Contents |
|---|---|
| [docs/AGENTS.md](docs/AGENTS.md) | Complete agent list, capabilities, and file paths |
| [docs/GUARDRAILS.md](docs/GUARDRAILS.md) | Validation layers, error handling, multi-agent patterns |
| [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) | Folder map and navigation guide |
| [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) | 10-minute presentation and live demo script |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, framework justification, tradeoffs |

---

## Demo & submission

For a live presentation, run `docker compose up --build` on your machine and
**share your screen** while navigating to http://localhost:3000. The app
runs locally — reviewers cannot open your `localhost` from their own computer
unless you deploy it or use a tunnel.

| Item | Status |
|---|---|
| GitHub repository | ✅ https://github.com/soniamannlehl-cloud/finalproject |
| `ARCHITECTURE.md` in repo root | ✅ |
| `README.md` with setup instructions | ✅ |
| Web UI (`frontend/`) | ✅ |
| Demo video (≤10 min) | ⬜ Record and add link below |
| Instructor has repo access | ⬜ Grant collaborator if private |

### Demo Video

<!-- Replace with your Canvas/YouTube/Loom link before submitting -->
`[Add your demo video link here]`

---

## License

See [LICENSE](LICENSE).
