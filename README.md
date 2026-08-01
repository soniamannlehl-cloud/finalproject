## Investment Research Platform

*Research a public company the way an investment firm would—using a team of AI analysts that work together, verify their findings, and keep you involved in the final decision.**

> ⚠️ **Academic capstone project.** This project was built as part of UCLA Extension's Agentic AI & Autonomous Systems course. It is for educational purposes only and is not investment advice.

---

## Demo Videos

| Video | Link |
| ----- | ---- |
| **Project Overview** | [Watch on Descript](https://share.descript.com/view/6yjRRA0YlL3) |
| **Platform Demo** | [Watch on Descript](https://share.descript.com/view/XdtJjAwLuML) |

---

## Why I Built It

Researching a company before investing isn't simple.

Professional investors don't make decisions based on one financial ratio or one news article. They gather information from many different sources, understand the company's industry, evaluate its financial performance, identify risks, compare competitors, and build an investment thesis before making a recommendation.

I wanted to see if a team of AI agents could work together the same way a professional investment research team does.

Instead of asking one AI assistant to do everything, I built a system where specialized AI agents each have a specific job and collaborate to produce a research report supported by evidence.

---

## What The Platform Does

Enter the name or ticker symbol of a public company.

The platform then:

Confirms you selected the correct company
Creates a research plan based on the company's industry
Assigns research tasks to specialized AI analysts
Collects information from financial data, SEC filings, earnings reports, news, and other trusted sources
Builds an investment thesis as new evidence is collected
Holds an AI investment committee discussion with both bullish and bearish viewpoints
Generates a complete investment research report
Waits for your approval before finalizing the recommendation

If there isn't enough evidence, the platform doesn't guess. Instead, it tells you that more research is needed.

---

## How It Works

```
You Enter a Company or ticker
          │
          ▼
Confirm the Correct Company
          │
          ▼
Create a Research Plan
          │
          ▼
Specialized AI Analysts Research the Company
          │
          ▼
Evidence is Collected
          │
          ▼
Investment Thesis is Built
          │
          ▼
AI Investment Committee Reviews the Evidence
          │
          ▼
You Review the Final Recommendation
          │
          ▼
Investment Research Report
```

---

## Key Features

| **Feature**                    | **What it Does**                                                                                                            | **Why it Matters**                                                                                    |
| ------------------------------ | --------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **Industry-Specific Research** | Creates a research plan based on the company's industry and business model.                                                 | A technology company shouldn't be analyzed the same way as a bank, REIT, or healthcare company.       |
| **Team of AI Analysts**        | Assigns specialized AI agents to research financials, valuation, competitors, news, risks, SEC filings, earnings, and more. | Each agent focuses on one area, creating a more complete research process than a single AI assistant. |
| **Research Planning**          | Builds a step-by-step research plan before any analysis begins.                                                             | Ensures the right questions are answered and the research follows a structured process.               |
| **Living Investment Thesis**   | Continuously updates the investment thesis as new evidence is collected.                                                    | The recommendation evolves with the research instead of being generated all at once.                  |
| **AI Investment Committee**    | Bull, Bear, and Chief Investment Officer (CIO) agents debate the investment case.                                           | Helps evaluate both positive and negative perspectives before reaching a recommendation.              |
| **Human Approval**             | Requires you to confirm the company before research begins and approve the final recommendation.                            | Keeps people involved in important decisions instead of letting AI work completely on its own.        |
| **Evidence-Based Research**    | Every conclusion must be supported by evidence collected during the research process.                                       | Makes it easier to understand how the recommendation was reached and reduces unsupported claims.      |
| **Built-in Guardrails**        | Checks for missing evidence, conflicting information, stale data, and unsupported conclusions.                              | Improves the reliability and transparency of the final report.                                        |


---

## System Architecture

The platform is organized into independent components, each responsible for a specific part of the investment research process.


| Component                         | Responsibility                                                                                                                        |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Web Application (Next.js)**     | Lets users start research, review findings, and approve recommendations.                                                              |
| **Workflow Engine (LangGraph)**   | Coordinates the entire research process, manages planning, human approval checkpoints, and report generation.                         |
| **Research Agents (A2A)**         | Specialized AI analysts that gather evidence on financials, valuation, industry, competitors, news, SEC filings, earnings, and risks. |
| **Investment Committee (CrewAI)** | Bull, Bear, and CIO agents debate the investment case before a recommendation is made.                                                |
| **Data Sources**                  | Financial statements, SEC filings, market data, and news used throughout the research process.                                        |
| **PostgreSQL**                    | Stores evidence, workflow state, checkpoints, and report history.                                                                     |


For full technical design, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Technology Stack
This project combines several AI frameworks, each chosen for a specific role.

| Framework        | Purpose                                                                    |
| ---------------- | -------------------------------------------------------------------------- |
| **LangGraph**    | Coordinates the research workflow and manages human approval steps         |
| **A2A Protocol** | Allows independent AI agents to communicate with one another               |
| **CrewAI**       | Simulates the investment committee discussion                              |
| **LangSmith**    | Tracks and evaluates how the AI agents reason through the research process |


**Course frameworks used:** LangGraph + HITL, A2A Protocol, CrewAI.

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
