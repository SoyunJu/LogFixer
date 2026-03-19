from typing import Optional
from pydantic import BaseModel


class SlackActionPayload(BaseModel):
    action_id: str      # APPROVE or REJECT
    log_hash: str
    user_name: str      # Who