# Automated Evaluation

Reproducible metrics for the capstone **Automated evaluation (+20 bonus)** rubric item.

## Quick run (requires live API)

```bash
docker compose up --build -d
pip install httpx
python evaluation/run_consistency.py --ticker NVDA --runs 2 --output evaluation/results.json
python evaluation/summarize_results.py evaluation/results.json
```

## Unit test suites (no Docker required for contracts)

```bash
# Shared contracts
pytest packages/contracts/tests -v

# API service (from services/api with venv)
pytest services/api/tests -v

# Specialists service
pytest services/specialists/tests -v
```

## What is measured

| Metric | Source |
|---|---|
| Recommendation action consistency | `run_consistency.py` — same ticker, N runs |
| Plan DAG validity | `packages/contracts/tests/test_contracts.py` |
| HITL routing | `services/api/tests/test_hitl_2.py` |
| Safety gating | `services/api/tests/test_safety.py` |
| Provider failover | `services/specialists/tests/` |

## Output

`run_consistency.py` writes JSON; `summarize_results.py` prints a markdown
summary suitable for inclusion in your submission or demo slides.
