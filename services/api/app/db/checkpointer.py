"""
Postgres checkpointer and run persistence.

The checkpointer is what makes HITL work at all. `interrupt()` suspends the
graph mid-execution; the run resumes on a later, separate HTTP request that
may land on a different worker process. Without durable checkpoints, the
in-flight state would be gone and both human checkpoints would be
unimplementable.

Postgres rather than SQLite: three containers, concurrent runs, and survival
across restarts.
"""

import logging
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg_pool import AsyncConnectionPool

from ..config import get_settings

log = logging.getLogger(__name__)

_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None


def _dsn() -> str:
    """psycopg wants `postgresql://`; normalize the SQLAlchemy-style prefix."""
    return get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")


async def init_checkpointer() -> AsyncPostgresSaver:
    """
    Open the pool and create checkpoint tables if absent.

    Called once at startup. `.setup()` is idempotent, so a restart against an
    existing database is a no-op rather than an error.
    """
    global _pool, _checkpointer

    if _checkpointer is not None:
        return _checkpointer

    _pool = AsyncConnectionPool(
        conninfo=_dsn(),
        max_size=10,
        min_size=1,
        # LangGraph's checkpointer issues multi-statement DDL during setup,
        # which fails inside psycopg's default implicit transaction.
        kwargs={"autocommit": True, "prepare_threshold": 0},
        open=False,
    )
    await _pool.open(wait=True)

    _checkpointer = AsyncPostgresSaver(_pool)
    await _checkpointer.setup()
    log.info("checkpointer ready")
    return _checkpointer


def get_checkpointer() -> AsyncPostgresSaver:
    if _checkpointer is None:
        raise RuntimeError("checkpointer not initialized; call init_checkpointer() at startup")
    return _checkpointer


async def close_checkpointer() -> None:
    global _pool, _checkpointer
    if _pool is not None:
        await _pool.close()
    _pool = None
    _checkpointer = None


@asynccontextmanager
async def db_cursor():
    """Cursor from the shared pool, for the application's own tables."""
    if _pool is None:
        raise RuntimeError("connection pool not initialized")
    async with _pool.connection() as conn, conn.cursor() as cur:
        yield cur


# --- application-level run tracking ----------------------------------------
# Distinct from LangGraph's checkpoint tables: this is the queryable index of
# runs for the UI ("show my recent research"), which checkpoint blobs cannot
# serve efficiently.


async def create_run(run_id: str, thread_id: str, ticker: str, status: str) -> None:
    async with db_cursor() as cur:
        await cur.execute(
            """
            INSERT INTO research_runs (run_id, ticker, status, thread_id)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (run_id) DO NOTHING
            """,
            (run_id, ticker, status, thread_id),
        )


async def update_run(
    run_id: str, *, status: str | None = None, ticker: str | None = None,
    company_name: str | None = None, completed: bool = False,
) -> None:
    sets, params = [], []
    if status is not None:
        sets.append("status = %s")
        params.append(status)
    if ticker is not None:
        sets.append("ticker = %s")
        params.append(ticker)
    if company_name is not None:
        sets.append("company_name = %s")
        params.append(company_name)
    if completed:
        sets.append("completed_at = now()")
    if not sets:
        return

    params.append(run_id)
    async with db_cursor() as cur:
        await cur.execute(f"UPDATE research_runs SET {', '.join(sets)} WHERE run_id = %s", params)


async def get_run(run_id: str) -> dict | None:
    async with db_cursor() as cur:
        await cur.execute(
            """
            SELECT run_id, ticker, company_name, status, thread_id, created_at, completed_at
            FROM research_runs WHERE run_id = %s
            """,
            (run_id,),
        )
        row = await cur.fetchone()

    if row is None:
        return None
    keys = ("run_id", "ticker", "company_name", "status", "thread_id", "created_at", "completed_at")
    return dict(zip(keys, row))


async def list_runs(limit: int = 20) -> list[dict]:
    async with db_cursor() as cur:
        await cur.execute(
            """
            SELECT run_id, ticker, company_name, status, created_at
            FROM research_runs ORDER BY created_at DESC LIMIT %s
            """,
            (limit,),
        )
        rows = await cur.fetchall()

    keys = ("run_id", "ticker", "company_name", "status", "created_at")
    return [dict(zip(keys, r)) for r in rows]
