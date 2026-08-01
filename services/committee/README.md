# Committee service (deliberation plane)

CrewAI investment committee: **Bull Analyst**, **Bear Analyst**, and **CIO**.

| File | Contents |
|------|----------|
| [`app/crew/committee.py`](app/crew/committee.py) | All three committee agents + crew execution |
| [`app/crew/brief.py`](app/crew/brief.py) | Evidence brief format fed to the committee |

The API service builds the brief (`services/api/app/committee/brief_builder.py`) and calls this service over HTTP. Committee agents **debate** — they do not fetch market data.

When running: http://localhost:8082/health
