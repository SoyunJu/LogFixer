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


    # 분석 트리거 (dev/test) -> prod 는 scheduler(RECEIVED) Auto ---------------------
@router.post("/{log_hash}/analyze", status_code=200)
async def analyze_incident(
        log_hash: str,
        db: AsyncSession = Depends(get_db),
):

    # 1) ANALYZING
    incident = await transition(db, log_hash, IncidentState.ANALYZING)

    # 2) LLM analyze
    result = await run_analyze(
        log_hash=log_hash,
        service_name=incident.service_name,
        summary=incident.summary or "",
        stack_trace=incident.stack_trace,
    )

    # 3) 검증
    is_valid, issues = validate(result)

    # 4) 분석 결과 DB 저장
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

        # Slack 승인 요청 발송
        from app.notification.slack import send_approval_request
        slack_ts = await send_approval_request(result=result, service_name=incident.service_name)

        # FOR thread reply , message this
        if slack_ts:
            incident.slack_ts = slack_ts
            await db.commit()
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

    # Execute 트리거
@router.post("/{log_hash}/execute", status_code=200)
async def execute_incident(
        log_hash: str,
        host: str,          # Server ip
        db: AsyncSession = Depends(get_db),
):

    # dev/test 트리거
    import json
    from app.agent.action_registry import get_action
    from app.agent.rollback import rollback_actions
    from app.notification.slack import send_execution_report

    # 1) state -> EXECUTING 변경 (Need Approval)
    incident = await transition(db, log_hash, IncidentState.EXECUTING)

    # 2) DB search solutions list
    solutions_raw = incident.solutions_json or "[]"
    solutions = json.loads(solutions_raw)

    actions_taken = []       # success action descript
    rollback_cmds = []       # success action command
    all_success = True

    for sol in solutions:
        action_type = sol.get("action_type", "")
        action = get_action(action_type)

        if action is None:
            logger.warning("[Execute] 알 수 없는 action_type=%s", action_type)
            continue

        result = await action.execute(
            host=host,
            target=sol.get("target"),
            config_key=sol.get("config_key"),
            config_value=sol.get("config_value"),
        )

        if result.success:
            actions_taken.append(f"{action_type}: {result.message} ✅")
            if result.rollback_cmd:
                rollback_cmds.append(result.rollback_cmd)
        else:
            actions_taken.append(f"{action_type}: {result.message} ❌")
            all_success = False
            logger.warning("[Execute] 액션 실패 logHash=%s action=%s", log_hash, action_type)
            break  # 하나라도 실패하면 중단 후 롤백

    # Success -> Noti , Fail -> Rollback
    if all_success:
        await send_execution_report(
            log_hash=log_hash,
            service_name=incident.service_name,
            actions_taken=actions_taken,
            elapsed_minutes=0,
            original_ts=incident.slack_ts,
        )
        logger.info("[Execute] 실행 완료 logHash=%s", log_hash)
        final_state = "EXECUTING"  # Need Approval
    else:
        await transition(db, log_hash, IncidentState.ROLLING_BACK)
        rollback_results = await rollback_actions(host=host, rollback_cmds=rollback_cmds)

        # Retry Count
        incident.retry_count += 1
        await db.commit()

        if incident.retry_count < 3:
            await transition(db, log_hash, IncidentState.RECEIVED)
            final_state = "RECEIVED"
        else:
            await transition(db, log_hash, IncidentState.ESCALATED)
            final_state = "ESCALATED"

        logger.warning("[Execute] 롤백 완료 logHash=%s retry=%d", log_hash, incident.retry_count)

    return {
        "logHash": log_hash,
        "state": final_state,
        "actionsTaken": actions_taken,
        "allSuccess": all_success,
    }

    # Resolved -> POST LogCollector
@router.post("/{log_hash}/resolve", status_code=200)
async def resolve_incident(
        log_hash: str,
        db: AsyncSession = Depends(get_db),
):

    from app.reporter.kb_updater import report_to_lc

    incident = await transition(db, log_hash, IncidentState.RESOLVED)
    logger.info("[Resolve] RESOLVED 처리 완료 logHash=%s", log_hash)

    # LC에 상태변경 + addendum 저장
    lc_ok = await report_to_lc(incident)
    if not lc_ok:
        logger.warning("[Resolve] LC 상태 변경 실패 logHash=%s", log_hash)

    return {
        "logHash": log_hash,
        "state": "RESOLVED",
        "lcReported": lc_ok,
    }

