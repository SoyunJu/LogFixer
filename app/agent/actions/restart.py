
import logging

from app.agent.actions.base import ActionResult, BaseAction
from app.agent.ssh_executor import run_ssh_command

logger = logging.getLogger(__name__)


class RestartAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "RESTART"

    async def execute(self, host: str, **kwargs) -> ActionResult:
        target = kwargs.get("target", "")
        if not target:
            return ActionResult(success=False, message="target(서비스명)이 없음")

        # Command ###########
        cmd = f"sudo systemctl restart {target}"
        rollback_cmd = f"sudo systemctl restart {target}"

        success, output = await run_ssh_command(host=host, command=cmd)

        if success:
            return ActionResult(
                success=True,
                message=f"{target} 재시작 완료",
                rollback_cmd=rollback_cmd,
            )
        else:
            return ActionResult(
                success=False,
                message=f"{target} 재시작 실패: {output}",
                rollback_cmd=rollback_cmd,
            )