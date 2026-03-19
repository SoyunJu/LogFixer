
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.core.enums import IncidentState
from app.db.models import LfIncident
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()

    # 30s check (logging)
async def _check_executing() -> None:

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(LfIncident).where(
                LfIncident.state == IncidentState.EXECUTING
            )
        )
        incidents = result.scalars().all()

        if incidents:
            logger.info("[Scheduler] EXECUTING 상태 incident %d건 감지", len(incidents))
            for inc in incidents:
                logger.warning(
                    "[Scheduler] EXECUTING stuck? logHash=%s updatedAt=%s",
                    inc.log_hash, inc.updated_at,
                )

    # 5m Monitoring
async def _check_recurrence() -> None:

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(LfIncident).where(
                LfIncident.state == IncidentState.RECEIVED,
                LfIncident.repeat_count >= 5,
                )
        )
        incidents = result.scalars().all()

        for inc in incidents:
            logger.warning(
                "[Scheduler] 고빈도 재발 incident logHash=%s repeatCount=%d",
                inc.log_hash, inc.repeat_count,
            )


def start_scheduler() -> None:

    scheduler.add_job(
        _check_executing,
        trigger="interval",
        seconds=30,
        id="check_executing",
        replace_existing=True,
    )

    scheduler.add_job(
        _check_recurrence,
        trigger="interval",
        minutes=5,
        id="check_recurrence",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] 스케줄러 시작 완료")


def stop_scheduler() -> None:

    if scheduler.running:
        scheduler.shutdown()
        logger.info("[Scheduler] 스케줄러 종료")