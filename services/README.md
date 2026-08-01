# Services

Three Python backends + one shared contracts package. Each service has its own `Dockerfile` and `requirements.txt`.

| Service | Port | Folder | Purpose |
|---------|------|--------|---------|
| **api** | 8080 | [`api/`](api/) | Orchestrates the research workflow (LangGraph) |
| **specialists** | 8081 | [`specialists/`](specialists/) | Runs research agents that fetch & analyze data (A2A) |
| **committee** | 8082 | [`committee/`](committee/) | Bull / Bear / CIO investment committee (CrewAI) |

Shared types: [`../packages/contracts/`](../packages/contracts/)

Full map: [`../docs/PROJECT_STRUCTURE.md`](../docs/PROJECT_STRUCTURE.md)  
Agent list: [`../docs/AGENTS.md`](../docs/AGENTS.md)
