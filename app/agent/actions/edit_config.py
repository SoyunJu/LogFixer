
import logging

from app.agent.actions.base import ActionResult, BaseAction
from app.agent.ssh_executor import run_ssh_command

logger = logging.getLogger(__name__)


class EditConfigAction(BaseAction):

    @property
    def action_type(self) -> str:
        return "EDIT_CONFIG"

    async def execute(self, host: str, **kwargs) -> ActionResult:
        target = kwargs.get("target", "")    # config path
        config_key = kwargs.get("config_key", "")
        config_value = kwargs.get("config_value", "")

        if not all([target, config_key, config_value]):
            return ActionResult(
                success=False,
                message="target(파일경로), config_key, config_value 모두 필요",
            )

        # Before : BACK UP ######
        backup_cmd = f"grep '^{config_key}' {target} || echo '{config_key}=UNKNOWN'"
        _, current_value = await run_ssh_command(host=host, command=backup_cmd)

        # Execute
        cmd = (
            f"grep -q '^{config_key}' {target} "
            f"&& sudo sed -i 's/^{config_key}=.*/{config_key}={config_value}/' {target} "
            f"|| echo '{config_key}={config_value}' | sudo tee -a {target}"
        )
        rollback_cmd = (
            f"sudo sed -i 's/^{config_key}=.*/{current_value}/' {target}"
        )

        success, output = await run_ssh_command(host=host, command=cmd)

        if success:
            return ActionResult(
                success=True,
                message=f"{target} 설정 변경: {config_key}={config_value}",
                rollback_cmd=rollback_cmd,
            )
        else:
            return ActionResult(
                success=False,
                message=f"설정 변경 실패: {output}",
                rollback_cmd=rollback_cmd,
            )