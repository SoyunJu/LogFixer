import logging

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.incident import IncidentResponse, IncidentWebhookRequest
from app.status.machine import get_incident, upsert_incident

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/incident", tags=["Incident"])
    # 202 check -> async analyze -------------------------------------------
@router.post("", status_code=202)
async def receive_incident(
        payload: IncidentWebhookRequest,
        db: AsyncSession = Depends(get_db),
):

    incident = await upsert_incident(db, payload)
    logger.info("[Webhook] 수신 완료 logHash=%s state=%s", incident.log_hash, incident.state)
    return {"logHash": incident.log_hash, "state": incident.state}



    # Helper : Loghash -> Incident detail search ---------------------------------
@router.get("/{log_hash}", response_model=IncidentResponse)
async def get_incident_detail(
        log_hash: str,
        db: AsyncSession = Depends(get_db),
):
    incident = await get_incident(db, log_hash)
    return IncidentResponse.model_validate(incident)