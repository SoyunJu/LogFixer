import logging
import json

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.incident import IncidentResponse, IncidentWebhookRequest
from app.analyzer.llm_analyzer import analyze as run_analyze
from app.analyzer.validator import validate
from app.core.enums import IncidentState
from app.status.machine import get_incident, transition, upsert_incident

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


    # 분석 트리거 (dev/test) -> prod 는 scheduler(RECEIVED) Auto
@router.post("/{log_hash}/analyze", status_code=200)
async def analyze_incident(
        log_hash: str,
        db: AsyncSession = Depends(get_db),
):

    # ANALYZING
    incident = await transition(db, log_hash, IncidentState.ANALYZING)

    # LLM analyze
    result = await run_analyze(
        log_hash=log_hash,
        service_name=incident.service_name,
        summary=incident.summary or "",
        stack_trace=incident.stack_trace,
    )

    # 검증
    is_valid, issues = validate(result)

    # 분석 결과 DB 저장
    incident.root_cause = result.root_cause
    incident.confidence = result.confidence
    incident.solutions_json = json.dumps(
        [s.model_dump() for s in result.solutions], ensure_ascii=False
    )
    incident.rag_sources_json = json.dumps(result.rag_sources, ensure_ascii=False)
    await db.commit()

    if is_valid:
        await transition(db, log_hash, IncidentState.PENDING_APPROVAL)
        logger.info("[Analyze] 검증 통과 → PENDING_APPROVAL logHash=%s", log_hash)
    else:
        logger.warning("[Analyze] 검증 실패 logHash=%s issues=%s", log_hash, issues)

    return {
        "logHash": log_hash,
        "state": incident.state,
        "rootCause": result.root_cause,
        "confidence": result.confidence,
        "solutions": [s.model_dump() for s in result.solutions],
        "valid": is_valid,
        "issues": issues,
    }