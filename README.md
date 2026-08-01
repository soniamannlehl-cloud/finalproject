# AI Investment Research Analyst

**A multi-agent AI system that simulates how a professional investment research firm analyzes a public company — with cited evidence, human approval gates, and the ability to refuse a recommendation when data is insufficient.**

> ⚠️ **Academic capstone project.** This is not investment advice.

---

## The Problem

Investment research is slow, expensive, and easy to get wrong. A single analyst must pull financials, compare peers, read filings, track news, assess risks, and form a view — often under time pressure. When AI is added to this workflow, new problems appear: models **invent numbers**, **skip verification**, and **always sound confident** even when evidence is thin.

The challenge is not “make an LLM summarize a 10-K.” It is: **how do you design an autonomous system that plans its work, gathers traceable evidence, checks its own conclusions, and knows when to stop?**

---

## The Solution

This project models a **research desk**, not a chatbot. You enter a ticker; the system:

1. **Confirms the company** with you before spending time or API cost
2. **Plans** an industry-specific research strategy (a bank is not analyzed like a REIT)
3. **Dispatches specialist agents** in parallel to gather real data from market and regulatory sources
4. **Builds a living investment thesis** that updates as evidence arrives
5. **Runs safety checks** on coverage, citations, and contradictions
6. **Convenes an investment committee** — Bull, Bear, and CIO — that debates only from verified evidence
7. **Generates a structured report** and waits for your **final approval** before anything is finalized

If evidence is too weak, the system returns **Insufficient Evidence** instead of a reckless Buy/Sell call.

---

## How It Works

```
You enter a ticker
       │
       ▼
Checkpoint #1 ──▶ Confirm company
       │
       ▼
Planner selects industry profile ──▶ Research plan (task DAG)
       │
       ▼
Director dispatches specialists in parallel ──▶ Evidence stored in Postgres
       │
       ▼
Thesis updates ──▶ Safety review ──▶ Committee debate (Bull / Bear / CIO)
       │
       ▼
Policy gate applies rules ──▶ Report generated
       │
       ▼
Checkpoint #2 ──▶ You approve, reject, or request more research
```

**Design principle:** the control plane *decides*, the data plane *retrieves*, the committee *argues*. No single agent does everything, and no recommendation ships without a human in the loop.

---

## Key Features

| Feature | Why it matters |
|---------|----------------|
| **Web dashboard** | Start research, watch progress, and approve checkpoints in a browser |
| **Industry-aware planning** | 13 industry profiles tailor metrics, valuation methods, and risk rules |
| **10 specialist agents** | Financials, valuation, risk, peers, news, SEC filings, earnings, and more |
| **Living investment thesis** | Versioned stance with a structured analyst framework (drivers, risks, catalysts) |
| **Safety pipeline** | Coverage checks, citation integrity, stale-data flags, contradiction detection |
| **Adversarial committee** | Bull and Bear must argue opposing cases before the CIO decides |
| **Deterministic policy gate** | Rules — not the LLM — have the final say on Buy / Hold / Sell |
| **Two human checkpoints** | Confirm before research; review the full report before finalize |
| **Graceful degradation** | Runs without paid data APIs; gaps are disclosed, not hidden |

---

## System Architecture

The system is split into **three independent Python services** plus a web frontend. Each service uses the framework best suited to its role, connected over HTTP with a shared contract layer.

```
  Next.js frontend (:3000)
        │
        ▼
  ┌───────────────┐   A2A/HTTP   ┌──────────────────┐
  │ API service   │─────────────▶│ Specialists      │──▶ Yahoo Finance · SEC
  │ (LangGraph)   │              │ (research agents)│    FMP · News · Polygon
  │ Control plane │              │ Data plane       │
  └───────┬───────┘              └──────────────────┘
          │ A2A/HTTP             ┌──────────────────┐
          ├─────────────────────▶│ Committee        │
          │                      │ (CrewAI)         │
          │                      │ Bull · Bear · CIO│
          │                      └──────────────────┘
          ▼
     PostgreSQL  ◀── evidence, thesis history, workflow checkpoints
```

| Component | Port | Role |
|-----------|------|------|
| Frontend | 3000 | Dashboard and human approval UI |
| API | 8080 | Workflow orchestration, planning, safety, reports |
| Specialists | 8081 | Data retrieval and analysis agents |
| Committee | 8082 | Adversarial investment debate |
| Postgres | 5432 | Persistent evidence and checkpoints |

For full technical design, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Technology Stack

| Layer | Technologies |
|-------|--------------|
| **Frontend** | Next.js, React, TypeScript, Tailwind CSS |
| **Orchestration** | LangGraph, FastAPI, PostgreSQL |
| **Research agents** | A2A protocol, FastAPI, Python |
| **Committee** | CrewAI |
| **Shared contracts** | Pydantic (framework-agnostic schemas) |
| **Data sources** | Yahoo Finance, SEC EDGAR, FMP, NewsAPI, Tavily, Polygon |
| **Observability** | LangSmith (optional) |
| **Infrastructure** | Docker Compose |

**Course frameworks used:** LangGraph + HITL, A2A Protocol, CrewAI (minimum required: 2).

---

## Screenshots

<!-- Add PNG/JPG files to docs/screenshots/ and uncomment the lines below -->

<!--
### Home — start a research run
![Start research](docs/screenshots/home.png)

### Checkpoint #1 — confirm company
![Company confirmation](docs/screenshots/checkpoint-1.png)

### Research in progress — evidence and thesis
![Live research dashboard](docs/screenshots/research-progress.png)

### Checkpoint #2 — review report and recommendation
![Final approval](docs/screenshots/checkpoint-2.png)

### Investment report
![Generated report](docs/screenshots/report.png)
-->

Screenshots are not yet checked into the repo. To add them:

1. Capture images while running the app at http://localhost:3000
2. Save to `docs/screenshots/` (e.g. `home.png`, `checkpoint-2.png`)
3. Uncomment the block above

**Demo video:** `[Add your demo video link here]`

---

## Installation

**Prerequisites**

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- An [OpenAI API key](https://platform.openai.com/api-keys)

**Setup**

```bash
git clone https://github.com/soniamannlehl-cloud/finalproject.git
cd finalproject

cp .env.example .env
# Open .env and set OPENAI_API_KEY=sk-...
```

---

## Running the Project

Start all services:

```bash
docker compose up --build
```

Wait until containers are healthy:

```bash
docker compose ps
```

Open the app:

| URL | Purpose |
|-----|---------|
| **http://localhost:3000** | **Main UI** — start here |
| http://localhost:8080/docs | API documentation |
| http://localhost:8081/agents | Specialist agent registry |

**Quick test run:** enter a ticker (e.g. `NVDA` or `AAPL`) → confirm at Checkpoint #1 → watch research progress → review the report at Checkpoint #2.

### Optional API keys

Only `OPENAI_API_KEY` is required. Other keys improve data coverage; missing keys are handled gracefully and noted in the report.

| Key | Required | Purpose |
|-----|----------|---------|
| `OPENAI_API_KEY` | Yes | Agent reasoning |
| `LANGSMITH_API_KEY` | Recommended | End-to-end tracing |
| `FMP_API_KEY` | Optional | Financial statements |
| `NEWSAPI_KEY` / `TAVILY_API_KEY` | Optional | News coverage |
| `POLYGON_API_KEY` | Optional | Market quotes |

---

## Project Structure

```
finalproject/
├── frontend/                 Next.js dashboard
├── services/
│   ├── api/                  Workflow orchestration (LangGraph)
│   ├── specialists/          Research agents + data tools
│   └── committee/            Bull / Bear / CIO debate (CrewAI)
├── packages/contracts/       Shared schemas + industry profiles
├── docs/                     Agent reference, guardrails, demo script
├── evaluation/               Consistency testing harness
└── ARCHITECTURE.md           Full system design document
```

| Looking for… | Start here |
|--------------|------------|
| Every agent and what it does | [docs/AGENTS.md](docs/AGENTS.md) |
| Folder-by-folder map | [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md) |
| Guardrails and validation | [docs/GUARDRAILS.md](docs/GUARDRAILS.md) |
| Presentation demo script | [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md) |

---

## Future Improvements

- **Per-run cost controls** — token and dollar budgets per research session
- **Cloud deployment** — hosted demo URL for reviewers (today runs locally)
- **More industry profiles** — broader sector coverage beyond the current 13
- **Queue-backed dispatch** — resilient specialist execution with retries at scale
- **Richer evaluation harness** — automated consistency scoring across tickers and runs

---

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).
