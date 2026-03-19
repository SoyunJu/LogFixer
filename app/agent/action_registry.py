
from app.agent.actions.base import BaseAction
from app.agent.actions.clear_memory import ClearMemoryAction
from app.agent.actions.del_disk import DelDiskAction
from app.agent.actions.edit_config import EditConfigAction
from app.agent.actions.restart import RestartAction

    # Action Mapping Class -> action_type : executor().py
_REGISTRY: dict[str, BaseAction] = {
    "RESTART":      RestartAction(),
    "EDIT_CONFIG":  EditConfigAction(),
    "DEL_DISK":     DelDiskAction(),
    "CLEAR_MEMORY": ClearMemoryAction(),
}



def get_action(action_type: str) -> BaseAction | None:
    return _REGISTRY.get(action_type)

def list_action_types() -> list[str]:
    return list(_REGISTRY.keys())