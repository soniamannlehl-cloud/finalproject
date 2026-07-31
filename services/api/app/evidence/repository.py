"""
Evidence repository.

Evidence is append-only and lives in Postgres, not in LangGraph state.
LangGraph checkpoints the whole state object on every superstep, so keeping
filing text and article bodies out of it is what stops checkpoints from
growing into the megabytes and slowing resume.

The workflow carries `evidence_ids`; this module is the only thing that
turns those IDs back into content. That indirection is also what makes
citations verifiable at report time: a claim referencing an ID that does not
resolve here is, by definition, fabricated.
"""

import json
import logging

from contracts import Claim, Evidence

from ..db.checkpointer import db_cursor

log = logging.getLogger(__name__)


async def save_evidence(items: list[Evidence]) -> list[str]:
    """
    Persist evidence, ignoring duplicates.

    `evidence_id` is content-addressed, so a retry that re-fetches unchanged
    data collides on the primary key and is skipped -- dedup comes free from
    the ID scheme rather than needing a separate check.
    """
    if not items:
        return []

    async with db_cursor() as cur:
        for ev in items:
            await cur.execute(
                """
                INSERT INTO evidence (
                    evidence_id, run_id, task_id, agent_id, capability,
                    source_type, source_name, source_url, citation,
                    content, summary, as_of_date, retrieved_at,
                    confidence, provider_degraded
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (evidence_id) DO NOTHING
                """,
                (
                    ev.evidence_id, ev.run_id, ev.task_id, ev.agent_id, ev.capability,
                    ev.source_type.value, ev.source_name, ev.source_url, ev.citation,
                    json.dumps(ev.content, default=str), ev.summary,
                    ev.as_of_date, ev.retrieved_at, ev.confidence, ev.provider_degraded,
                ),
            )

    return [ev.evidence_id for ev in items]


async def save_claims(claims: list[Claim]) -> list[str]:
    if not claims:
        return []

    async with db_cursor() as cur:
        for claim in claims:
            await cur.execute(
                """
                INSERT INTO claims (
                    claim_id, run_id, text, evidence_ids, confidence,
                    polarity, category, author_agent_id, created_at
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (claim_id) DO NOTHING
                """,
                (
                    claim.claim_id, claim.run_id, claim.text, claim.evidence_ids,
                    claim.confidence, claim.polarity.value, claim.category,
                    claim.author_agent_id, claim.created_at,
                ),
            )

    return [c.claim_id for c in claims]


async def get_evidence_for_run(run_id: str) -> list[dict]:
    """All evidence for a run, newest first."""
    async with db_cursor() as cur:
        await cur.execute(
            """
            SELECT evidence_id, task_id, agent_id, capability, source_type,
                   source_name, source_url, citation, content, summary,
                   as_of_date, retrieved_at, confidence, provider_degraded
            FROM evidence WHERE run_id = %s ORDER BY retrieved_at DESC
            """,
            (run_id,),
        )
        rows = await cur.fetchall()

    keys = (
        "evidence_id", "task_id", "agent_id", "capability", "source_type",
        "source_name", "source_url", "citation", "content", "summary",
        "as_of_date", "retrieved_at", "confidence", "provider_degraded",
    )
    return [dict(zip(keys, row)) for row in rows]


async def resolve_evidence_ids(evidence_ids: list[str]) -> set[str]:
    """
    Which of these IDs actually exist.

    The Evidence Validator uses this: any claim citing an ID absent from the
    returned set is unsupported, which hard-blocks a directional
    recommendation. Deterministic, and far more reliable than asking an LLM
    whether a citation looks real.
    """
    if not evidence_ids:
        return set()

    async with db_cursor() as cur:
        await cur.execute(
            "SELECT evidence_id FROM evidence WHERE evidence_id = ANY(%s)",
            (list(evidence_ids),),
        )
        rows = await cur.fetchall()

    return {row[0] for row in rows}


async def evidence_summary(run_id: str) -> dict:
    """Per-capability counts and confidence -- feeds coverage scoring."""
    async with db_cursor() as cur:
        await cur.execute(
            """
            SELECT capability, count(*), avg(confidence), bool_or(provider_degraded)
            FROM evidence WHERE run_id = %s GROUP BY capability
            """,
            (run_id,),
        )
        rows = await cur.fetchall()

    return {
        row[0]: {
            "count": row[1],
            "avg_confidence": float(row[2]) if row[2] is not None else 0.0,
            "degraded": row[3],
        }
        for row in rows
    }
