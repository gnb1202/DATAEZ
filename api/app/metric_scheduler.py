"""Database-backed scheduling; works across API workers without LLM calls.

The row lock covers query execution and result/schedule persistence. A crashed
worker rolls back, leaving the original due time for the next worker to claim.
"""

import asyncio
import logging

from .db import _connect
from .dashboard_metrics import refresh_locked

logger = logging.getLogger(__name__)


def refresh_one_due() -> bool:
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("""SELECT w.id, w.user_id, w.project_id, w.widget_data,
                    w.refresh_interval_seconds, w.refresh_failures
                    FROM dashboard_widgets w JOIN projects p ON p.id=w.project_id AND p.user_id=w.user_id
                    WHERE w.next_refresh_at <= now() AND w.refresh_interval_seconds > 0
                    AND w.widget_data ? 'metric_definition' AND p.deleted_at IS NULL
                    ORDER BY w.next_refresh_at LIMIT 1 FOR UPDATE OF w SKIP LOCKED""")
        row = cur.fetchone()
        if not row:
            return False
        _, failure = refresh_locked(conn, cur, row, str(row["id"]), str(row["user_id"]), str(row["project_id"]))
        conn.commit()
        if failure:
            logger.warning("Scheduled metric %s failed: %s", row["id"], failure)
        return True


async def run_metric_scheduler(stop: asyncio.Event):
    while not stop.is_set():
        try:
            # Bound each batch so shutdown and other background tasks get time.
            for _ in range(20):
                if stop.is_set() or not await asyncio.to_thread(refresh_one_due):
                    break
        except Exception:
            logger.exception("Metric scheduler tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=15)
        except TimeoutError:
            pass
