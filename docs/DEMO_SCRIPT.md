# 10-Minute Presentation & Demo Script

Use this script for your capstone video (max 10 minutes). It is structured
to hit the rubric: architecture rationale, live demo, HITL checkpoints, and
at least one failure/edge case.

---

## Part 1: Presentation (≈4 minutes)

### Slide 1 — Problem (30 sec)
"We built an AI Investment Research Analyst that simulates professional due
diligence — not a chatbot. It plans research, gathers cited evidence, debates
via an investment committee, and requires human approval."

### Slide 2 — Architecture diagram (60 sec)
Show `ARCHITECTURE.md` §2 diagram. Explain three services:
- **API (LangGraph)** — orchestrates workflow and HITL
- **Specialists (A2A)** — 9 research agents over HTTP
- **Committee (CrewAI)** — Bull, Bear, CIO debate

Key invariant: control plane *decides*, data plane *retrieves*, committee *argues*.

### Slide 3 — Framework justification (90 sec)
"We use **three** course frameworks (minimum is two):

1. **LangGraph + HITL** — `interrupt()` pauses workflow for human approval; Postgres checkpointing survives restarts.
2. **A2A Protocol** — specialists are separately deployed; Director discovers capabilities at runtime.
3. **CrewAI** — adversarial role-play for Bull/Bear/CIO; bounded debate, not open-ended chat.

We evaluated **Google ADK** and rejected it — specialists are retrieval workloads, not autonomous reasoners. See ARCHITECTURE.md §3."

### Slide 4 — Planning paradigm (60 sec)
"The Planner emits a `ResearchPlan` — a data artifact, not hardcoded steps.
Industry playbooks change metrics: banks get ROE/NIM; REITs get FFO/NAV.
Replanning at HITL #2 produces a new revision; Director dispatches only the delta."

---

## Part 2: Live Demo (≈5 minutes)

**Prerequisites:** `docker compose up --build` running; `.env` has `OPENAI_API_KEY`.

### Demo A — Happy path (3 min)

1. Open **http://localhost:3000**
2. Enter ticker **NVDA** → Start research
3. **HITL #1:** Show company confirmation screen → click **Confirm**
4. Wait for research (show auto-refresh: evidence count, plan, thesis)
5. **HITL #2:** Show committee recommendation, bull/bear cases → click **Approve**
6. Show **Download PDF** / **View HTML report**
7. Optional: open **http://localhost:8080/docs** → `GET /runs/{id}/plan`, `/safety`, `/thesis`

### Demo B — Failure / edge case (2 min) — **REQUIRED by rubric**

Pick **one** of these (Failure #1 is easiest):

#### Failure #1: Invalid company (recommended)
1. Start new run with ticker **ZZZZINVALID**
2. Show system returns "not found" — does not crash
3. Point out: validation agent returns structured failure, workflow stops cleanly

#### Failure #2: Human rejects recommendation
1. Complete a run to HITL #2
2. Click **Reject** instead of Approve
3. Show status becomes `rejected`; report reflects human decision

#### Failure #3: Request more analysis (replan)
1. At HITL #2, click **Request more analysis**
2. Type feedback: "Need more valuation analysis"
3. Show system replans and re-dispatches only affected tasks

#### Failure #4: Specialist service down (advanced)
1. In another terminal: `docker stop irp-specialists`
2. Start a new run and confirm company
3. Show declared gaps in safety/report — workflow degrades, does not crash
4. Restart: `docker start irp-specialists`

#### Failure #5: LangSmith trace (if keyed)
1. Show LangSmith dashboard with a completed run trace
2. Point out planner → director → specialist spans

---

## Part 3: Close (≈1 minute)

"Limitations: bounded industry playbooks, no cross-session learning, committee
is the cost center. Future work: queue-backed dispatch, expanded playbooks.
Questions?"

---

## Recording Tips (Production quality — 20 points)

- Use 1080p screen recording; zoom browser to 125% for legibility
- Test microphone; quiet room
- Rehearse once to stay under 10 minutes
- Show terminal/docker only briefly — focus on the UI and one API docs page

---

## Video Submission

Add your link to README.md:

```markdown
## Demo Video
[Capstone Demo (10 min)](https://your-link-here)
```
