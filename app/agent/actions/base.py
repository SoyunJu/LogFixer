
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ActionResult:

    success: bool
    message: str
    rollback_cmd: str | None = None


# ############ action base class #########
class BaseAction(ABC):

    # host -> ssh , kwargs -> target, config_key, etc
    @abstractmethod
    async def execute(self, host: str, **kwargs) -> ActionResult:
        pass

    # RESTART / EDIT_CONFIG / DEL_DISK / CLEAR_MEMORY
    @property
    @abstractmethod
    def action_type(self) -> str:
        pass