
import logging

from app.agent.actions.base import ActionResult, BaseAction
from app.agent.ssh_executor import run_ssh_command

logger = logging.getLogger(__name__)

    # default path : /var/log, /tmp
class DelDiskAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "DEL_DISK"

    async def execute(self, host: str, **kwargs) -> ActionResult:

        target = kwargs.get("target", "/var/log")

        # 14일 이상 .log 삭제
        cmd = f"sudo find {target} -name '*.log' -mtime +14 -delete && echo 'done'"
        # del_disk -> ######## CAN'T ROLLBACK ###################
        rollback_cmd = None

        success, output = await run_ssh_command(host=host, command=cmd)

        if success:
            return ActionResult(
                success=True,
                message=f"{target} 2주 이상 로그 정리 완료",
                rollback_cmd=rollback_cmd,
            )
        else:
            return ActionResult(
                success=False,
                message=f"디스크 정리 실패: {output}",
                rollback_cmd=rollback_cmd,
            )