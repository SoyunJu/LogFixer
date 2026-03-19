
import json
import logging

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.core.enums import IncidentState
from app.db.models import LfIncident
from app.notification.slack import update_message
from app.status.machine import transition

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/slack", tags=["Slack"])


@router.post("/action")
async def handle_slack_action(
        request: Request,
        db: AsyncSession = Depends(get_db),
):

    # form body -> payload Key로 JSON 담기
    form_data = await request.form()
    payload_str = form_data.get("payload", "")

    try:
        payload = json.loads(payload_str)
    except (json.JSONDecodeError, TypeError):
        logger.warning("[Slack] payload 파싱 실패: %s", payload_str[:200])
        return {"ok": False, "error": "invalid payload"}

    actions = payload.get("actions", [])
    if not actions:
        return {"ok": True}

    action = actions[0]
    action_id = action.get("action_id")   # approve / reject / resolve
    log_hash = action.get("value", "")    # 식별용 log_hash

    # Who
    user_name = payload.get("user", {}).get("name", "unknown")

    # 메시지 this
    message_ts = payload.get("message", {}).get("ts")

    logger.info(
        "[Slack] 액션 수신 action_id=%s logHash=%s user=%s",
        action_id, log_hash, user_name,
    )

    # 승인 Approve ################################################
    if action_id == "approve":
        try:
            await transition(db, log_hash, IncidentState.EXECUTING)
            logger.info("[Slack] 승인 완료 logHash=%s user=%s", log_hash, user_name)

            if message_ts:
                await update_message(
                    ts=message_ts,
                    text=f"✅ {user_name}님이 승인했습니다. 실행 중... (logHash: {log_hash})",
                )
        except Exception as e:
            logger.error("[Slack] 승인 처리 실패 logHash=%s err=%s", log_hash, e)

    # 거절 Reject ##################################################
    elif action_id == "reject":
        try:
            await transition(db, log_hash, IncidentState.RECEIVED)
            logger.info("[Slack] 거절 됨. 재분석 로직... logHash=%s user=%s → RECEIVED", log_hash, user_name)

            if message_ts:
                await update_message(
                    ts=message_ts,
                    text=f"❌ {user_name}님이 거절했습니다. 재분석 대기 중... (logHash: {log_hash})",
                )
        except Exception as e:
            logger.error("[Slack] 거절 처리 실패 logHash=%s err=%s", log_hash, e)


    # RESOLVED 상태변경 승인 ##########################################
    elif action_id == "resolve":
        try:
            await transition(db, log_hash, IncidentState.RESOLVED)
            logger.info("[Slack] RESOLVED 처리 완료 logHash=%s user=%s", log_hash, user_name)

            if message_ts:
                await update_message(
                    ts=message_ts,
                    text=f"✅ {user_name}님이 RESOLVED 승인했습니다. (logHash: {log_hash})",
                )
        except Exception as e:
            logger.error("[Slack] RESOLVED 처리 실패 logHash=%s err=%s", log_hash, e)

    # Slack 로딩 스피너 제거용 -> 200 OK
    return {"ok": True}