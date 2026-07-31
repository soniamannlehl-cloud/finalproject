# Collaborative Investment Research Platform — Build Brief

## Revision note
This brief was revised to align with the instructor's actual assignment
spec: the Orchestrator drafts a recommendation with explicit reasoning
chains, and Checkpoint #2 is an investment-committee approval gate
(approve / reject / revise) before that recommendation is finalized — not
a free-form takeaway with no verdict. See `ARCHITECTURE.md`'s Technical
Analysis section for the full reasoning behind this change.

## What this is
A multi-agent system that helps beginner investors research a public
company. Specialist agents gather sentiment, financial, and macro/industry
evidence; the Orchestrator synthesizes it into a beginner-friendly memo
plus a draft recommendation, presented to a human investment committee for
approval, rejection, or revision before anything is finalized.

## Frameworks (exactly 2, per course requirement)
- **LangGraph with HITL** — the backbone graph, using `interrupt()`/resume for
  all human checkpoints.
- **A2A Protocol** — used specifically to route the Checkpoint #2 Q&A follow-up
  questions to the specific specialist agent that owns that topic (not through
  a generic orchestrator response).
- Do NOT add CrewAI, Google ADK, or n8n — deliberately scoped out (see
  ARCHITECTURE.md tradeoffs).

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
  research into clear, evidence-based investment memos and drafts a
  recommendation for an investment committee's review and approval —
  presenting patterns in the evidence, not issuing advice directly to an
  end investor."
- Input: all 3 specialists' outputs; on a revision round, also the prior
  draft_recommendation and the committee's feedback
- PRODUCT PRINCIPLE: the draft recommendation is a directional, analyst-style
  thesis conclusion (e.g. "Constructive", "Cautious", "Neutral" + rationale)
  drafted FOR the investment committee's review — it is never surfaced to an
  end investor and never finalized until a human approves it at Checkpoint #2.
  It is not personalized advice and never based on a stored user profile
  (there is no persistent user profile in this system — none should be built)
- PLANNING / TASK DECOMPOSITION (required by rubric, must be explicit and
  inspectable, not hard-coded): the Orchestrator must visibly decompose
  "build the memo + recommendation" into sequential reasoning sub-steps,
  stored in `reasoning_chain`: (1) identify evidence pattern, (2) identify
  the 2-3 most decision-relevant risk factors for THIS specific company
  (dynamic, not a fixed template), (3) identify invalidation triggers,
  (4) identify catalysts/timeline, (5) draft the recommendation itself.
  Each sub-step's output should be inspectable in LangSmith traces.
- REPLANNING ON REVISION: when the committee sends the memo back with
  feedback (`committee_decision == "revise"`), the Orchestrator re-runs all
  5 steps with the prior recommendation + committee feedback injected into
  every prompt, so the thesis is genuinely UPDATED to address the feedback
  — not regenerated from scratch and not just cosmetically reworded. This
  is the "building and updating an investment thesis as new data arrives"
  planning requirement.
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
  evidence_pattern_classification, data_gaps, draft_recommendation,
  revision_count
- Owns HITL Checkpoint #2 (see below) and A2A-routed Q&A

## End-to-end graph flow (exact node/edge sequence for graph.py)

This is the authoritative flow.

```
START
  │
  ▼
[Node: intake_validation]
  - LLM extracts likely company candidate from raw user input
  - Calls ticker-search tool on the extracted candidate
  - Branches on result:
      match found      → set intake_status="confirmed", go to Checkpoint #1
      no match          → LLM classifies: private company vs. not-found/typo
                          → set intake_status accordingly
                          → message user, this turn ends (next user message
                            re-enters intake_validation for a fresh attempt)
  │ (match found)
  ▼
[HITL interrupt: Checkpoint #1 — Company Validation]
  - Show candidate company/ticker, ask user Yes/No
  - No  → this turn ends, next message retries [Node: intake_validation]
  - Yes → set checkpoint_1_approved=True, continue
  │
  ├─────────────────────┬─────────────────────────────┐
  ▼                      ▼                              
[Node: sentiment_analyst] [Node: industry_identification] (deterministic,
  - runs immediately,      no LLM call)
    no industry needed     - looks up industry/sector from ticker
  │                        - feeds Financial + Macro nodes below
  ▼                                 │
[Node: sentiment_sync]    ┌──────────┴──────────┐
  - no-op barrier;        ▼                      ▼
    exists only to  [Node: financial_analyst] [Node: macro_industry_analyst]
    equalize path     - waits on industry        - waits on industry
    depth with the    - universal ratios first
    financial/macro    - then industry ratios
    path below (a                │                      │
    LangGraph 1.2.10   │          │                      │
    limitation, see    └──────────┴──────────────────────┘
    ARCHITECTURE.md)              │
  │                               │
  └───────────────────────────────┤
                                   ▼
              [Node: data_failure_check] (deterministic — no LLM)
                - reads sentiment_failed, financial_failed, macro_failed
                - 0-2 failed → set data_gaps, continue to Orchestrator
                - all 3 failed → HITL interrupt: tell user, offer retry
                                 → retry restarts from the industry_identification
                                   + sentiment_analyst fan-out point
  │ (proceeds)
  ▼
[Node: build_memo] (Orchestrator, step 1/2)
  - explicit reasoning_chain steps: pattern → risk factors →
    invalidation triggers → catalysts → draft_recommendation
  - produces memo fields + draft_recommendation
  │
  ▼
[HITL interrupt: Checkpoint #2 — Investment Committee Approval] ◄────┐
  - Show memo + draft_recommendation (headline first, expandable)    │
  - Loop: committee may ask follow-up questions                      │
      → [A2A route_question] determines which specialist owns the    │
         question's topic, dispatches to that agent, returns answer, │
         appends to checkpoint_2_qa_history                          │
      → back to interrupt, committee may ask another question or     │
        render a decision                                            │
  - Decision: approve | reject | revise (+ feedback)                 │
      - approve/reject → set committee_decision, status="complete" → END
      - revise → set committee_decision="revise", committee_feedback,
        route back to [Node: build_memo] to update the thesis ───────┘
        (capped at MAX_REVISION_ROUNDS, then auto-closed as rejected)
  │
  ▼
END
```

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
   time, not just on ambiguous matches. No → this turn ends; retry on the
   next message.
2. **Checkpoint #2 — Investment Committee Approval**: after the Orchestrator
   produces the memo + draft recommendation, interrupt to show both (headline
   first, expandable detail). The committee can ask open-ended follow-up
   questions, which route via A2A Protocol to the SPECIFIC specialist agent
   that owns that topic (a sentiment question → Sentiment Analyst, not
   answered generically by Orchestrator) — stored in `checkpoint_2_qa_history`.
   The committee must then render a genuine decision, not a rubber stamp:
   - **Approve** → `committee_decision="approved"`, recommendation finalized,
     session ends.
   - **Reject** → `committee_decision="rejected"`, recommendation is not
     finalized, session ends.
   - **Revise** (+ required feedback) → `committee_decision="revise"`,
     `committee_feedback` set, routes back to the Orchestrator, which
     updates its reasoning chain and recommendation to address the feedback,
     then re-presents an updated Checkpoint #2. Capped at `MAX_REVISION_ROUNDS`
     to prevent an infinite loop; past that, auto-closes as rejected.
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
1. The draft recommendation is written FOR the investment committee's review
   and is never surfaced to an end investor or treated as finalized until a
   human explicitly approves it at Checkpoint #2 — no autonomous action on
   a recommendation the system produces.
2. All financial/trend calculations are deterministic code, never LLM math.
3. No persistent user risk-profile storage — nothing stored across sessions
   about the user's risk tolerance/goals.
4. Memo language is beginner-friendly by design, enforced via system prompt,
   not an afterthought.
5. Data failures are always disclosed transparently, never silently defaulted.
6. Every Q&A follow-up routes to the specific owning specialist via A2A, not
   answered generically.
7. Checkpoint #2 is a genuine decision point (approve/reject/revise), not a
   rubber-stamp confirmation — "revise" must measurably change the
   Orchestrator's next output, not just log the feedback and ignore it.

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
