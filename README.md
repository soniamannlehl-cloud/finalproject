# Collaborative Investment Research Platform

A multi-agent LangGraph system that helps research a public company.
Specialist agents gather sentiment, financial, and macro/industry evidence;
the Orchestrator synthesizes it into a beginner-friendly memo plus a draft
recommendation, which a human investment committee must approve, reject, or
send back for revision before anything is finalized.

See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for the full design spec and
`ARCHITECTURE.md` for the system diagram, framework justification, and
tradeoffs.

## Setup

**Requires Python 3.11+.**

```bash
python3.11 -m venv .venv
```

Activate it, then install dependencies:

```bash
.venv/Scripts/pip install -r requirements.txt      # Windows
# .venv/bin/pip install -r requirements.txt        # macOS/Linux
```

Copy `.env.example` to `.env` and fill in API keys:

```bash
cp .env.example .env
```

| Key | Required? | Used for | Get one at |
|---|---|---|---|
| `OPENAI_API_KEY` | Yes, unless using Google | Default LLM (`LLM_PROVIDER=openai`) | platform.openai.com |
| `GOOGLE_API_KEY` | Only if `LLM_PROVIDER=google` | Alternate LLM | aistudio.google.com |
| `ALPHA_VANTAGE_API_KEY` | Recommended | Fallback for financial data + news (25 req/day free tier) | alphavantage.co/support/#api-key |
| `NEWSAPI_KEY` | Recommended | Primary news source for Sentiment + Macro/Industry analysts | newsapi.org/register |
| `FRED_API_KEY` | Recommended | Macro indicators (GDP, CPI, fed funds, unemployment) | fred.stlouisfed.org/docs/api/api_key.html |
| `LANGSMITH_API_KEY` | Optional | Traces the Orchestrator's 5-step reasoning chain | smith.langchain.com |

The system degrades gracefully without the "recommended" keys (yfinance
covers financial data and sector ETF performance on its own; missing news
keys just mean the Sentiment Analyst and Macro/Industry landscape layer
report themselves as unavailable rather than failing the whole run).

## Running it

There's no CLI or frontend in this build (see `PROJECT_BRIEF.md`'s file
structure) -- `graph.py` exposes `compile_graph()`, which you drive with
LangGraph's own `invoke()` / `Command(resume=...)` pattern. A minimal
driver:

```python
from langgraph.types import Command
from graph import compile_graph
from state import get_initial_state

app = compile_graph()  # uses CHECKPOINT_DB from .env
config = {"configurable": {"thread_id": "session-1"}}

# Turn 1: kick off research
result = app.invoke(get_initial_state("Tesla"), config)
print(result["__interrupt__"])  # Checkpoint #1: confirm the matched ticker

# Resume with the user's yes/no
result = app.invoke(Command(resume="yes"), config)
print(result["__interrupt__"])  # Checkpoint #2: memo + draft_recommendation, ready for committee review

# Ask a follow-up (routed via A2A to the owning specialist)
result = app.invoke(
    Command(resume={"action": "question", "question": "How risky is this?"}),
    config,
)
print(result["__interrupt__"])  # same checkpoint, updated qa_history

# Send it back for revision -- the Orchestrator updates its thesis and
# recommendation to address the feedback, then re-presents Checkpoint #2
result = app.invoke(
    Command(resume={
        "action": "decision",
        "decision": "revise",
        "feedback": "Address customer concentration risk before we approve.",
    }),
    config,
)
print(result["__interrupt__"])  # updated memo + draft_recommendation, revision_count incremented

# Approve (or reject) to finalize -- nothing is finalized before this point
result = app.invoke(
    Command(resume={
        "action": "decision",
        "decision": "approve",
        "feedback": "Concentration risk now adequately addressed.",
    }),
    config,
)
print(result["status"])  # "complete"
print(result["committee_decision"])  # "approved"
```

If the user says "no" at Checkpoint #1, or the company can't be resolved
(private company / not found), the graph run ends for that turn -- start a
new `invoke()` with a fresh `raw_user_input` to try again under the same
`thread_id` (conversation history persists via the checkpointer). A
"revise" decision is capped at `MAX_REVISION_ROUNDS` (default 3, in
`config.py`) -- past that, the session auto-closes as rejected rather than
looping forever.

## Project layout

See `PROJECT_BRIEF.md` for the full file-by-file spec. Key entry points:

- [state.py](state.py) -- `InvestmentResearchState` schema + `get_initial_state()`
- [config.py](config.py) -- env loading, `get_llm()` factory, thresholds
- [graph.py](graph.py) -- StateGraph wiring, interrupts, routing
- `agents/` -- the 5 agents (Intake, Sentiment, Financial, Macro & Industry, Orchestrator)
- `tools/` -- deterministic calculations, news search, A2A router
- `data/` -- industry ratio + sector indicator lookup tables

## Known limitations

- Sentiment Analyst's path to `data_failure_check` runs through a trivial
  no-op node, `sentiment_sync` (see `graph.py`'s module docstring). It
  exists only to give that path the same hop-depth as Financial/Macro
  Analyst's path (via `industry_identification`) -- an asymmetric-depth
  fan-in at that point reproducibly corrupted execution in LangGraph 1.2.10
  once combined with the Checkpoint #2 multi-turn interrupt loop.
- The Alpha Vantage fallback path for financial data doesn't populate
  industry/sector (its taxonomy doesn't match `data/industry_ratios.json`'s
  yfinance-based keys), so a fallback-sourced company always gets the
  universal ratio set only.
- `data/industry_ratios.json` and `data/sector_indicators.json` cover a
  curated set of common industries with a sector-level fallback, not
  yfinance's full industry taxonomy (hundreds of values).
