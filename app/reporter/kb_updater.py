
import asyncio
import logging
from datetime import datetime

import httpx
from pytz import timezone

from app.core.config import settings
from app.db.models import LfIncident
from app.reporter.generator import generate_actions_taken, generate_addendum_content

logger = logging.getLogger(__name__)

# LC API 재시도 설정
MAX_RETRY = 5
RETRY_DELAY_SEC = 3

# KST 타임존
kst = timezone('Asia/Seoul')


############ LogCollector API Call Module ############################

# PATCH Incident Status
async def _patch_incident_status(log_hash: str, status: str = "RESOLVED") -> bool:
    url = f"{settings.LC_BASE_URL}/api/incidents/{log_hash}/status"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(
                url,
                params={"newStatus": status},
                timeout=10,
            )
            if response.status_code == 200:
                logger.info("[LC] 상태 변경 완료 logHash=%s status=%s", log_hash, status)
                return True
            else:
                logger.warning(
                    "[LC] 상태 변경 실패 logHash=%s status=%d body=%s",
                    log_hash, response.status_code, response.text[:200],
                )
                return False
        except Exception as e:
            logger.error("[LC] 상태 변경 오류 logHash=%s err=%s", log_hash, e)
            return False


    # GET kbArticleId
async def _get_kb_article_id(log_hash: str) -> str | None:
    url = f"{settings.LC_BASE_URL}/api/kb/articles/byhash/{log_hash}"

    for attempt in range(1, MAX_RETRY + 1):
        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(url, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    kb_article_id = data.get("kbArticleId") or data.get("id")
                    if kb_article_id:
                        logger.info(
                            "[LC] kbArticleId 조회 완료 logHash=%s id=%s",
                            log_hash, kb_article_id,
                        )
                        return str(kb_article_id)
                logger.warning(
                    "[LC] kbArticleId 조회 시도 %d/%d 실패 logHash=%s status=%d",
                    attempt, MAX_RETRY, log_hash, response.status_code,
                )
            except Exception as e:
                logger.warning(
                    "[LC] kbArticleId 조회 시도 %d/%d 오류 logHash=%s err=%s",
                    attempt, MAX_RETRY, log_hash, e,
                )

        if attempt < MAX_RETRY:
            await asyncio.sleep(RETRY_DELAY_SEC)

    logger.error("[LC] kbArticleId 조회 최종 실패 logHash=%s", log_hash)
    return None


    # POST KB Addendum
async def _post_addendum(
        kb_article_id: str,
        content: str,
        actions_taken: list[str],
) -> bool:
    url = f"{settings.LC_BASE_URL}/api/kb/{kb_article_id}/addendums"

    actions_text = "\n".join(f"- {a}" for a in actions_taken)
    full_content = f"{content}\n\n[실행 내역]\n{actions_text}" if actions_taken else content

    body = {
        "title": "LogFixer 자동 해결 보고",
        "content": full_content,
        "createdBy": "system",  # LC enum: system / user / admin
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=body, timeout=10)
            if response.status_code == 200:
                logger.info("[LC] addendum 저장 완료 kbArticleId=%s", kb_article_id)
                return True
            else:
                logger.warning(
                    "[LC] addendum 저장 실패 kbArticleId=%s status=%d body=%s",
                    kb_article_id, response.status_code, response.text[:200],
                )
                return False
        except Exception as e:
            logger.error("[LC] addendum 저장 오류 kbArticleId=%s err=%s", kb_article_id, e)
            return False


    ############### LC API 순서대로 호출 ###########################
async def report_to_lc(incident: LfIncident) -> bool:
    log_hash = incident.log_hash

    # 1) PATCH /api/incidents/{logHash}/status
    status_ok = await _patch_incident_status(log_hash)
    if not status_ok:
        logger.error("[Reporter] LC 상태 변경 실패로 중단 logHash=%s", log_hash)
        return False

    # 2) GET /api/kb/articles/byhash/{logHash}
    kb_article_id = await _get_kb_article_id(log_hash)
    if not kb_article_id:
        logger.error("[Reporter] kbArticleId 확보 실패로 addendum 저장 불가 logHash=%s", log_hash)
        return False

    # 3) POST /api/kb/{kbArticleId}/addendums
    content = generate_addendum_content(incident)
    actions_taken = generate_actions_taken(incident)
    addendum_ok = await _post_addendum(kb_article_id, content, actions_taken)

    if addendum_ok:
        logger.info("[Reporter] LC 전체 보고 완료 logHash=%s", log_hash)
    else:
        logger.warning("[Reporter] addendum 저장 실패 logHash=%s", log_hash)

    return addendum_ok