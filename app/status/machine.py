import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import IncidentState
from app.core.exceptions import (
    IncidentNotFoundException,
    InvalidStateTransitionException,
)
from app.db.models import LfIncident
from app.schemas.incident import IncidentWebhookRequest

logger = logging.getLogger(__name__)

ALLOWED_TRANSITIONS: dict[IncidentState, list[IncidentState]] = {
    IncidentState.RECEIVED:         [IncidentState.ANALYZING],
    IncidentState.ANALYZING:        [IncidentState.PENDING_APPROVAL],
    IncidentState.PENDING_APPROVAL: [IncidentState.EXECUTING, IncidentState.RECEIVED],
    IncidentState.EXECUTING:        [IncidentState.RESOLVED, IncidentState.ROLLING_BACK],
    IncidentState.ROLLING_BACK:     [IncidentState.RECEIVED, IncidentState.ESCALATED],
    IncidentState.RESOLVED:         [],
    IncidentState.ESCALATED:        [],
}

# webhook -> upsert -------------------------------------------------------------
async def upsert_incident(
        db: AsyncSession,
        payload: IncidentWebhookRequest,
) -> LfIncident:

    result = await db.execute(
        select(LfIncident).where(LfIncident.log_hash == payload.logHash)
    )
    incident = result.scalar_one_or_none()

    if incident is None:
        # New Webhook: RECEIVED state
        incident = LfIncident(
            log_hash=payload.logHash,
            service_name=payload.serviceName,
            summary=payload.summary,
            stack_trace=payload.stackTrace,
            error_code=payload.errorCode,
            log_level=payload.logLevel,
            impacted_host_count=payload.impactedHostCount,
            repeat_count=payload.repeatCount,
            occurred_at=payload.occurredTime,
            state=IncidentState.RECEIVED,
        )
        db.add(incident)
        logger.info("[Incident][NEW] logHash=%s service=%s", payload.logHash, payload.serviceName)
    else:
        # repeat : time, count update
        incident.repeat_count = payload.repeatCount
        incident.impacted_host_count = payload.impactedHostCount
        incident.occurred_at = payload.occurredTime
        logger.info("[Incident][UPDATE] logHash=%s repeatCount=%d", payload.logHash, payload.repeatCount)

    await db.commit()
    await db.refresh(incident)
    return incident


 # allowed state update ------------------------------------------------------
async def transition(
        db: AsyncSession,
        log_hash: str,
        target: IncidentState,
) -> LfIncident:

    result = await db.execute(
        select(LfIncident).where(LfIncident.log_hash == log_hash)
    )
    incident = result.scalar_one_or_none()

    if incident is None:
        raise IncidentNotFoundException(log_hash)

    allowed = ALLOWED_TRANSITIONS.get(incident.state, [])
    if target not in allowed:
        raise InvalidStateTransitionException(incident.state, target)

    incident.state = target
    logger.info(
        "[Incident][TRANSITION] logHash=%s %s → %s",
        log_hash, incident.state, target,
    )

    await db.commit()
    await db.refresh(incident)
    return incident

 # Helper : Loghash -> Incident search ----------------------------------------------------
async def get_incident(
        db: AsyncSession,
        log_hash: str,
) -> LfIncident:

    result = await db.execute(
        select(LfIncident).where(LfIncident.log_hash == log_hash)
    )
    incident = result.scalar_one_or_none()

    if incident is None:
        raise IncidentNotFoundException(log_hash)

    return incident