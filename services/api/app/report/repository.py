"""Report persistence — stores serialized InvestmentReport payloads."""

import json
import logging
from datetime import datetime, timezone

from contracts import InvestmentReport

from ..db.checkpointer import db_cursor

log = logging.getLogger(__name__)


async def save_report(report: InvestmentReport) -> str:
    async with db_cursor() as cur:
        await cur.execute(
            """
            INSERT INTO reports (
                report_id, run_id, ticker, payload, approved_by_human, generated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (report_id) DO UPDATE SET payload = EXCLUDED.payload
            """,
            (
                report.report_id,
                report.run_id,
                report.ticker,
                json.dumps(report.model_dump(mode="json"), default=str),
                report.approved_by_human,
                report.generated_at,
            ),
        )
    return report.report_id


async def get_report(run_id: str) -> InvestmentReport | None:
    async with db_cursor() as cur:
        await cur.execute(
            """
            SELECT payload FROM reports WHERE run_id = %s
            ORDER BY generated_at DESC LIMIT 1
            """,
            (run_id,),
        )
        row = await cur.fetchone()

    if not row:
        return None
    return InvestmentReport.model_validate(row[0])


async def mark_report_approved(run_id: str) -> None:
    """Stamp human approval on the latest report for a run."""
    report = await get_report(run_id)
    if report is None:
        return
    report.approved_by_human = True
    report.approved_at = datetime.now(timezone.utc)
    await save_report(report)
