"""
Thesis version persistence.

Versions are append-only. The thesis is never updated in place, because the
platform's claim is that the thesis *evolves as evidence arrives* -- and an
overwritten string cannot demonstrate that. Keeping every revision, with the
reason it changed and the task that triggered it, turns "the thesis evolves"
from an assertion into something you can display: v1 -> v4 with the
rationale for each step.
"""

import logging

from contracts import Polarity, ThesisHistory, ThesisVersion

from ..db.checkpointer import db_cursor

log = logging.getLogger(__name__)


async def save_thesis_version(version: ThesisVersion) -> int:
    """Append one thesis revision. Idempotent on (run_id, version)."""
    async with db_cursor() as cur:
        await cur.execute(
            """
            INSERT INTO thesis_versions (
                run_id, version, parent_version, statement, stance, confidence,
                supporting_claim_ids, contradicting_claim_ids,
                change_reason, triggered_by, created_at
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (run_id, version) DO NOTHING
            """,
            (
                version.run_id, version.version, version.parent_version,
                version.statement, version.stance.value, version.confidence,
                version.supporting_claim_ids, version.contradicting_claim_ids,
                version.change_reason, version.triggered_by, version.created_at,
            ),
        )
    return version.version


async def get_latest_version(run_id: str) -> ThesisVersion | None:
    """Most recent revision, or None before the first one exists."""
    async with db_cursor() as cur:
        await cur.execute(
            """
            SELECT run_id, version, parent_version, statement, stance, confidence,
                   supporting_claim_ids, contradicting_claim_ids,
                   change_reason, triggered_by, created_at
            FROM thesis_versions WHERE run_id = %s
            ORDER BY version DESC LIMIT 1
            """,
            (run_id,),
        )
        row = await cur.fetchone()

    return _row_to_version(row) if row else None


async def get_history(run_id: str) -> ThesisHistory:
    """Full revision chain, oldest first -- the evolution record."""
    async with db_cursor() as cur:
        await cur.execute(
            """
            SELECT run_id, version, parent_version, statement, stance, confidence,
                   supporting_claim_ids, contradicting_claim_ids,
                   change_reason, triggered_by, created_at
            FROM thesis_versions WHERE run_id = %s ORDER BY version ASC
            """,
            (run_id,),
        )
        rows = await cur.fetchall()

    return ThesisHistory(run_id=run_id, versions=[_row_to_version(r) for r in rows])


def _row_to_version(row) -> ThesisVersion:
    return ThesisVersion(
        run_id=row[0],
        version=row[1],
        parent_version=row[2],
        statement=row[3],
        stance=Polarity(row[4]),
        confidence=row[5],
        supporting_claim_ids=list(row[6] or []),
        contradicting_claim_ids=list(row[7] or []),
        change_reason=row[8],
        triggered_by=row[9],
        created_at=row[10],
    )
