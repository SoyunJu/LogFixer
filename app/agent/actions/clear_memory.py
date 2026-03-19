
import logging

from app.agent.actions.base import ActionResult, BaseAction
from app.agent.ssh_executor import run_ssh_command

logger = logging.getLogger(__name__)

    # drop cache mem
class ClearMemoryAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "CLEAR_MEMORY"

    async def execute(self, host: str, **kwargs) -> ActionResult:

        cmd = "sync && echo 3 | sudo tee /proc/sys/vm/drop_caches"
        # clear_mem -> ####### CAN'T ROLLBACK ####################
        rollback_cmd = None

        success, output = await run_ssh_command(host=host, command=cmd)

        if success:
            return ActionResult(
                success=True,
                message="캐시 메모리 정리 완료",
                rollback_cmd=rollback_cmd,
            )
        else:
            return ActionResult(
                success=False,
                message=f"메모리 정리 실패: {output}",
                rollback_cmd=rollback_cmd,
            )