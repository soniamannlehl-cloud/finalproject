# Specialists service (data plane)

Research agents that retrieve data, compute metrics, and return **evidence**.

## Where the agents are

```
app/agents/          ← ★ START HERE — one file per agent
app/a2a/cards.py     ← Registry: which file handles which capability
app/tools/           ← Shared data/compute helpers (not agents)
```

| File | Agent |
|------|-------|
| `company_validation.py` | Match ticker to public company |
| `company_profile.py` | Business description, sector, industry |
| `financial_analyst.py` | Statements + industry-specific ratios |
| `valuation_analyst.py` | Peer-relative valuation |
| `risk_analyst.py` | Industry-aware risk flags |
| `investment_driver_agent.py` | KPI & investment driver assessment |
| `competitor_analyst.py` | Peer comparison |
| `news_analyst.py` | News sentiment |
| `sec_filings.py` | SEC EDGAR filings |
| `earnings_analyst.py` | Earnings beats/misses |

## Adding a new agent

1. Create `app/agents/my_agent.py` with `AGENT_ID` and `handle(inputs, run_id, task_id)`
2. Register in `app/a2a/cards.py`
3. Add capability to `packages/contracts/src/contracts/enums.py`
4. Add to relevant industry profile in `packages/contracts/.../industry_profiles/profiles.py`

Discovery endpoint (when running): http://localhost:8081/agents

Tests: [`tests/`](tests/)
