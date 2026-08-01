# API service (control plane)

LangGraph workflow: plan → dispatch → thesis → safety → committee → report → human approval.

## Key entry points

| What | File |
|------|------|
| Workflow graph | [`app/graph/builder.py`](app/graph/builder.py) |
| REST API | [`app/api/routes.py`](app/api/routes.py) |
| Research Planner | [`app/planning/planner.py`](app/planning/planner.py) |
| Research Director | [`app/director/director.py`](app/director/director.py) |
| Thesis agent | [`app/thesis/agent.py`](app/thesis/agent.py) |
| Safety pipeline | [`app/safety/pipeline.py`](app/safety/pipeline.py) |
| Report generator | [`app/report/generator.py`](app/report/generator.py) |

## Workflow nodes

```
app/graph/nodes/
├── validate.py      HITL #1 — confirm company
├── committee.py     Call committee service
├── synthesizer.py   Apply policy gate to recommendation
├── report.py        Build HTML/PDF report
└── hitl_2.py        HITL #2 — human approves or replans
```

This service **does not** call Yahoo Finance or SEC directly. It sends tasks to the **specialists** service via A2A.

Tests: [`tests/`](tests/)
