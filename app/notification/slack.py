
import json
import logging
from typing import Optional

from slack_sdk.web.async_client import AsyncWebClient

from app.core.config import settings
from app.schemas.analysis import AnalysisResult

logger = logging.getLogger(__name__)

# Slack Async client
_slack_client: Optional[AsyncWebClient] = None


def get_slack_client() -> AsyncWebClient:
    global _slack_client
    if _slack_client is None:
        _slack_client = AsyncWebClient(token=settings.SLACK_BOT_TOKEN)
    return _slack_client


def _build_approval_blocks(result: AnalysisResult, service_name: str) -> list[dict]:

    solution_lines = ""
    for sol in result.solutions:
        solution_lines += f"\n  {sol.rank}. [{sol.action_type}] {sol.description}"
        if sol.target:
            solution_lines += f" (`{sol.target}`)"

    sources_text = ", ".join(result.rag_sources) if result.rag_sources else "연관 KB가 없습니다."

    confidence_pct = int(result.confidence * 100)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": " [LogFixer] 장애 분석 완료 | 승인 요청 "},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*서비스:* `{service_name}`\n"
                    f"*원인:* {result.root_cause}\n"
                    f"*신뢰도:* {confidence_pct}%\n"
                    f"*해결법:*{solution_lines}\n"
                    f"*근거:* {sources_text}"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ 승인"},
                    "style": "primary",
                    "action_id": "approve",
                    "value": result.log_hash,       # 식별용 loghash
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "❌ 재분석"},
                    "style": "danger",
                    "action_id": "reject",
                    "value": result.log_hash,       # 식별용 loghash
                },
            ],
        },
    ]
    return blocks


def _build_report_blocks(
        log_hash: str,
        service_name: str,
        actions_taken: list[str],
        elapsed_minutes: int,
) -> list[dict]:

    actions_text = "\n".join(f"  - {a}" for a in actions_taken)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "[LogFixer] AI Agent 장애 해결 보고 "},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*서비스:* `{service_name}`\n"
                    f"*소요 시간:* {elapsed_minutes}분\n"
                    f"*실행 내역:*\n{actions_text}"
                ),
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✅ RESOLVED 승인"},
                    "style": "primary",
                    "action_id": "resolve",
                    "value": log_hash,      # 식별용 log_hash
                },
            ],
        },
    ]
    return blocks


        # ########### Helper #################
async def send_approval_request(result: AnalysisResult, service_name: str) -> Optional[str]:

    client = get_slack_client()
    blocks = _build_approval_blocks(result, service_name)

    try:
        response = await client.chat_postMessage(
            channel=settings.SLACK_CHANNEL_ID,
            blocks=blocks,
            text=f"[LogFixer] {service_name} 장애 분석 완료 | 승인 요청",
        )
        ts = response["ts"]
        logger.info("[Slack] 승인 요청 발송 완료 logHash=%s ts=%s", result.log_hash, ts)
        return ts
    except Exception as e:
        logger.error("[Slack] 발송 실패 logHash=%s err=%s", result.log_hash, e)
        return None


async def send_execution_report(
        log_hash: str,
        service_name: str,
        actions_taken: list[str],
        elapsed_minutes: int,
        original_ts: Optional[str] = None,
) -> Optional[str]:

    client = get_slack_client()
    blocks = _build_report_blocks(log_hash, service_name, actions_taken, elapsed_minutes)

    try:
        kwargs = {
            "channel": settings.SLACK_CHANNEL_ID,
            "blocks": blocks,
            "text": f"[LogFixer] {service_name} AI Agent 장애 해결 보고 ",
        }
        # if existing thread ###########################################
        if original_ts:
            kwargs["thread_ts"] = original_ts

        response = await client.chat_postMessage(**kwargs)
        ts = response["ts"]
        logger.info("[Slack] 보고 완료 logHash=%s ts=%s", log_hash, ts)
        return ts
    except Exception as e:
        logger.error("[Slack] 알림 발송 실패 logHash=%s err=%s", log_hash, e)
        return None


 # ######### 버튼 제거용 ##################
async def update_message(ts: str, text: str) -> None:
    client = get_slack_client()
    try:
        await client.chat_update(
            channel=settings.SLACK_CHANNEL_ID,
            ts=ts,
            text=text,
            blocks=[],  # 버튼 제거
        )
        logger.info("[Slack] 메시지 업데이트 완료 ts=%s", ts)
    except Exception as e:
        logger.error("[Slack] 메시지 업데이트 실패 ts=%s err=%s", ts, e)