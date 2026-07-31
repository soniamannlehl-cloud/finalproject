# Collaborative Investment Research Platform — Build Brief

## What this is
A multi-agent system that helps beginner investors research a public company.
It does NOT give buy/sell advice — it presents evidence and explains patterns
in plain language, and lets the user reach their own conclusion.

## Frameworks (exactly 2, per course requirement)
- **LangGraph with HITL** — the backbone graph, using `interrupt()`/resume for
  all human checkpoints.
- **A2A Protocol** — used specifically to route the Checkpoint #2 Q&A follow-up
  questions to the specific specialist agent that owns that topic (not through
  a generic orchestrator response).
- Do NOT add CrewAI, Google ADK, or n8n — deliberately scoped out (see
  ARCHITECTURE.md tradeoffs, to be written after code is working).

## Agents (5 total) + 1 deterministic step

### 1. Intake & Validation Agent
- Persona: "You are a financial data specialist responsible for accurately
  identifying publicly traded companies from user descriptions."
- Input: raw user text (e.g. "Tesla", "the Delta situation", "AAPL")
- Tool: ticker/company search (yfinance search or Alpha Vantage SYMBOL_SEARCH)
- Logic:
  - Match found → present ticker/company name → **HITL Checkpoint #1**:
    interrupt(), ask user to confirm Yes/No. No → loop back to input.
  - No match → LLM reasons (no external tool) whether input is a real but
    likely-private company, or unrecognized/typo. Respond accordingly:
    - Private: explain we can't research private companies, ask to try again
    - Not found: ask user to try full name or ticker symbol
  - Output sets `intake_status`: "confirmed" | "private_company" | "not_found"

### Industry Identification (deterministic, NOT an agent — no LLM call)
- Input: ticker
- Tool: yfinance `.info` sector/industry fields (or Alpha Vantage OVERVIEW)
- Output: industry, sector
- Runs in PARALLEL with Sentiment Analyst (both kick off right after
  Checkpoint #1 confirms), NOT sequentially before it

### 2. Sentiment Analyst Agent
- Persona: "You are an expert media and sentiment analyst who evaluates news
  coverage and public sentiment about companies."
- Input: company_name, ticker (does NOT need industry — starts immediately
  after Checkpoint #1, in parallel with Industry ID)
- Tool: shared `tools/news_search.py` module, called with scope="company"
- Output: sentiment_summary, key_articles, sentiment_trend (~30 day lookback),
  sentiment_data_as_of
- Must flag low-coverage companies rather than overstate confidence from
  few articles

### 3. Financial Analyst Agent
- Persona: "You are an expert financial analyst who evaluates the financial
  health of a company using industry-appropriate financial ratios and metrics."
- Input: ticker, industry (waits on Industry ID)
- Data source: yfinance PRIMARY, Alpha Vantage FALLBACK (yfinance has no
  official rate limit; Alpha Vantage free tier is 25 req/day, 5/min — too
  tight to rely on primarily)
- Flow:
  1. Pull raw financials (yfinance → Alpha Vantage fallback)
  2. Compute UNIVERSAL ratios first (always, every company) — deterministic
     Python functions, NOT LLM math: P/E, EPS, P/B, revenue growth, gross
     margin, operating margin, debt-to-equity, free cash flow
  3. Look up `data/industry_ratios.json` for this industry's specific ratio
     set, compute those too via deterministic functions
  4. LLM interprets the COMBINED computed results (never does the arithmetic
     itself)
- Tools: `tools/financial_calculations.py` (deterministic functions, one per
  ratio, with div-by-zero/undefined guards e.g. negative EPS → P/E flagged
  as not meaningful), `data/industry_ratios.json` (lookup table)
- Output: raw_financials, universal_ratios, industry_ratios,
  ratio_interpretation, financial_data_as_of
- Must flag incomplete/stale filings (recent IPOs, foreign issuers) rather
  than compute misleading ratios off partial data

### 4. Macro & Industry Analyst Agent
- Persona: "You are an expert macroeconomic and industry analyst who
  evaluates economic conditions, sector performance, and competitive
  dynamics."
- Input: industry, sector (waits on Industry ID)
- Three layers:
  1. Universal macro indicators (GDP growth, inflation/CPI, fed funds rate,
     unemployment) — pull CURRENT value AND trend (rising/falling/stable
     over 6-12mo) via FRED historical series + deterministic
     `tools/macro_calculations.py::compute_trend()`
  2. Sector ETF performance (universal — every company gets its sector ETF's
     performance) — current + 3mo/6mo/YTD trend + comparison vs S&P 500,
     via yfinance historical prices
  3. Industry-specific indicators — look up `data/sector_indicators.json`
     for this industry (e.g. banks: 10yr Treasury yield; airlines: oil price)
  4. Industry landscape (qualitative, LLM-driven, NOT deterministic) —
     search industry-level news via `tools/news_search.py` scope="industry"
     for competitive dynamics: new entrants, consolidation/M&A, regulatory
     shifts, business-model changes
- Output: macro_indicators {current, trend}, sector_performance {current,
  trend, vs_sp500}, industry_landscape {competitive_summary,
  notable_developments, key_sources}, macro_interpretation,
  macro_data_as_of

### 5. Orchestrator Agent
- Persona: "You are a senior research analyst who synthesizes specialist
  research into clear, evidence-based investment memos — presenting patterns
  in the evidence without issuing investment recommendations."
- Input: all 3 specialists' outputs
- CRITICAL PRODUCT PRINCIPLE: never issues buy/sell/hold verdicts. May
  classify the evidence pattern (e.g. "fits growth-style profile" vs.
  "fits value-style profile") as a DESCRIPTIVE classification of the
  evidence, never personalized advice, never based on a stored user profile
  (there is no persistent user profile in this system — none should be built)
- PLANNING / TASK DECOMPOSITION (required by rubric, must be explicit and
  inspectable, not hard-coded): the Orchestrator must visibly decompose
  "build the memo" into sequential reasoning sub-steps, stored in
  `reasoning_chain`: (1) identify evidence pattern, (2) identify the 2-3 most
  decision-relevant risk factors for THIS specific company (dynamic, not a
  fixed template), (3) identify invalidation triggers, (4) identify
  catalysts/timeline. Each sub-step's output should be inspectable in
  LangSmith traces.
- MEMO STYLE — CRITICAL, must be enforced in the system prompt:
  - Written for a beginner investor with NO finance background
  - Every technical term gets a plain-language gloss the FIRST time it
    appears (e.g. not just "P/E ratio: 24" but explain what that means)
  - Headline finding stated in one plain sentence FIRST, before any detail
  - Each section: plain-language takeaway first, supporting numbers/evidence
    after — never lead with numbers
  - No assumed background knowledge of finance jargon
- Output: headline_finding, thesis_summary, evidence_by_category,
  reasoning_chain, risk_factors, invalidation_triggers,
  evidence_pattern_classification, data_gaps
- Owns HITL Checkpoint #2 (see below) and A2A-routed Q&A

## Data-failure handling (error handling requirement)
After the 3 specialists run in parallel, before Orchestrator runs, check
`sentiment_failed`, `financial_failed`, `macro_failed`:
- 1 or 2 specialists failed → proceed automatically to Orchestrator, but
  populate `data_gaps` and require the memo to transparently flag which
  sections are limited/missing (e.g. "⚠️ Sentiment data was unavailable —
  this memo reflects financial and macro research only")
- ALL 3 failed → hard stop, `interrupt()`, tell user plainly research
  couldn't be completed, offer retry. This is the ONLY data-related
  interrupt — partial failures do not interrupt the user.

## HITL Checkpoints (LangGraph interrupt/resume)
1. **Checkpoint #1 — Company Validation**: after Intake Agent resolves a
   candidate match, ALWAYS interrupt and ask user Yes/No to confirm — every
   time, not just on ambiguous matches. No → loop back to input.
2. **Checkpoint #2 — Memo Review + Q&A**: after Orchestrator produces the
   memo, interrupt to show the user the memo (headline first, expandable
   detail). Then open-ended Q&A: user can ask follow-up questions, which
   route via A2A Protocol to the SPECIFIC specialist agent that owns that
   topic (a sentiment question → Sentiment Analyst, not answered generically
   by Orchestrator). Store each Q&A exchange in `checkpoint_2_qa_history`.
   Session closes with the user's own free-form takeaway
   (`user_takeaway`) — no forced approve/reject, no system verdict.
3. **Total data failure interrupt** (see above) — third, narrower interrupt.

## State schema
Already built — see `state.py` in this repo. Use `InvestmentResearchState`
(extends LangGraph's `MessagesState`) and the `get_initial_state()` helper.
Do not redesign the schema; extend it only if a genuine gap is found while
coding.

## File/folder structure to build
```
/finalproject
  state.py                       (already exists — do not overwrite)
  config.py                      (API keys via .env, rate-limit constants,
                                   thresholds)
  graph.py                       (StateGraph wiring: nodes, edges,
                                   conditional routing, interrupt points)
  /agents
    intake_validation.py
    sentiment_analyst.py
    financial_analyst.py
    macro_industry_analyst.py
    orchestrator.py
  /tools
    financial_calculations.py    (deterministic ratio functions)
    macro_calculations.py        (deterministic trend functions)
    news_search.py                (shared news API client, scope param)
  /data
    industry_ratios.json          (universal + industry_specific ratio lists)
    sector_indicators.json        (industry → extra macro indicators + ETF)
  requirements.txt
  .env.example
  README.md                      (setup instructions)
  ARCHITECTURE.md                (to be written once code works — 2-4 pages,
                                   diagram, framework justification, tradeoffs)
```

## Non-negotiable principles (do not let the LLM drift from these)
1. Never issue a buy/sell/hold recommendation anywhere in the system.
2. All financial/trend calculations are deterministic code, never LLM math.
3. No persistent user risk-profile storage — nothing stored across sessions
   about the user's risk tolerance/goals.
4. Memo language is beginner-friendly by design, enforced via system prompt,
   not an afterthought.
5. Data failures are always disclosed transparently, never silently defaulted.
6. Every Q&A follow-up routes to the specific owning specialist via A2A, not
   answered generically.

## Build order
1. config.py
2. data/industry_ratios.json + data/sector_indicators.json
3. tools/financial_calculations.py, tools/macro_calculations.py,
   tools/news_search.py
4. agents/ (one at a time, in the order listed above)
5. graph.py (wire everything together, add interrupts)
6. Test end-to-end with a real company
7. requirements.txt + README.md
8. ARCHITECTURE.md last, once the working system exists to document
