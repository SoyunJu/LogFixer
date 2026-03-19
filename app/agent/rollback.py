
import logging

from app.agent.ssh_executor import run_ssh_command

logger = logging.getLogger(__name__)


async def rollback_actions(
        host: str,
        rollback_cmds: list[str],
) -> list[dict]:

    results = []

    # execute Desc
    for cmd in reversed(rollback_cmds):
        logger.info("[Rollback] 실행: %s", cmd[:80])
        success, output = await run_ssh_command(host=host, command=cmd)
        results.append({
            "cmd": cmd,
            "success": success,
            "output": output[:200],
        })
        if not success:
            logger.warning("[Rollback] 실패: %s → %s", cmd[:80], output[:200])

    return results