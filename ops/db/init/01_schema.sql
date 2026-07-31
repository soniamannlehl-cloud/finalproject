-- ===========================================================================
-- AI Investment Research Platform -- initial schema
-- ===========================================================================
-- Runs automatically on first Postgres container start.
--
-- Design note: this database holds the LARGE, immutable artifacts (evidence
-- payloads, thesis history, reports). LangGraph state deliberately holds only
-- IDs that point here, because LangGraph checkpoints the entire state object
-- on every superstep -- putting filing text in state would make checkpoints
-- enormous and visibly slow down resume during a demo.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS research_runs (
    run_id          TEXT PRIMARY KEY,
    ticker          TEXT NOT NULL,
    company_name    TEXT,
    status          TEXT NOT NULL,
    thread_id       TEXT NOT NULL,          -- LangGraph checkpoint thread
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_runs_ticker ON research_runs (ticker);
CREATE INDEX IF NOT EXISTS idx_runs_status ON research_runs (status);


-- Evidence is append-only and never updated: an immutable audit trail is what
-- lets the report resolve every citation back to a specific retrieval.
CREATE TABLE IF NOT EXISTS evidence (
    evidence_id     TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES research_runs (run_id) ON DELETE CASCADE,
    task_id         TEXT NOT NULL,
    agent_id        TEXT NOT NULL,
    capability      TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_name     TEXT NOT NULL,
    source_url      TEXT,
    citation        TEXT NOT NULL,
    content         JSONB NOT NULL,
    summary         TEXT,
    as_of_date      TIMESTAMPTZ,
    retrieved_at    TIMESTAMPTZ NOT NULL,
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    provider_degraded BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_evidence_run ON evidence (run_id);
CREATE INDEX IF NOT EXISTS idx_evidence_capability ON evidence (run_id, capability);


CREATE TABLE IF NOT EXISTS claims (
    claim_id        TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES research_runs (run_id) ON DELETE CASCADE,
    text            TEXT NOT NULL,
    evidence_ids    TEXT[] NOT NULL,
    confidence      REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    polarity        TEXT NOT NULL,
    category        TEXT NOT NULL,
    author_agent_id TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Mirrors the Pydantic invariant: an uncited claim cannot exist at the
    -- schema layer either, so the guardrail survives a buggy writer.
    CONSTRAINT claims_must_cite_evidence CHECK (array_length(evidence_ids, 1) >= 1)
);

CREATE INDEX IF NOT EXISTS idx_claims_run ON claims (run_id);


-- Versioned rather than mutated, so the thesis's evolution is inspectable.
CREATE TABLE IF NOT EXISTS thesis_versions (
    run_id                  TEXT NOT NULL REFERENCES research_runs (run_id) ON DELETE CASCADE,
    version                 INTEGER NOT NULL,
    parent_version          INTEGER,
    statement               TEXT NOT NULL,
    stance                  TEXT NOT NULL,
    confidence              REAL NOT NULL,
    supporting_claim_ids    TEXT[] NOT NULL DEFAULT '{}',
    contradicting_claim_ids TEXT[] NOT NULL DEFAULT '{}',
    change_reason           TEXT NOT NULL,
    triggered_by            TEXT NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, version)
);


CREATE TABLE IF NOT EXISTS reports (
    report_id       TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES research_runs (run_id) ON DELETE CASCADE,
    ticker          TEXT NOT NULL,
    payload         JSONB NOT NULL,         -- serialized InvestmentReport
    approved_by_human BOOLEAN NOT NULL DEFAULT FALSE,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- Every external call is recorded: this is the raw material for the
-- observability story and for demonstrating failure handling.
CREATE TABLE IF NOT EXISTS tool_calls (
    id              BIGSERIAL PRIMARY KEY,
    run_id          TEXT NOT NULL,
    task_id         TEXT,
    provider        TEXT NOT NULL,
    endpoint        TEXT,
    status          TEXT NOT NULL,
    cache_hit       BOOLEAN NOT NULL DEFAULT FALSE,
    latency_ms      INTEGER,
    error           TEXT,
    called_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_run ON tool_calls (run_id);
