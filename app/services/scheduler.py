import asyncio
import logging
from datetime import datetime, timezone
from sqlalchemy import select
from app.db.session import SessionLocal
from app.models import Bank
from app.services.game import process_period

logger = logging.getLogger(__name__)

async def run_period_scheduler(stop_event: asyncio.Event, interval_seconds: int = 3600) -> None:
    """One process-wide worker; it never creates a task per user."""
    while not stop_event.is_set():
        try:
            async with SessionLocal() as session:
                user_ids = list((await session.scalars(select(Bank.user_id))).all())
            for user_id in user_ids:
                try:
                    async with SessionLocal() as session:
                        await process_period(session, user_id, datetime.now(timezone.utc))
                except Exception:
                    logger.exception("game period failed for user_id=%s", user_id)
        except Exception:
            logger.exception("period scheduler iteration failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            continue
