from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.core.enums import IncidentState


 # webhook Body
class IncidentWebhookRequest(BaseModel):
    logHash: str
    serviceName: str
    summary: Optional[str] = None
    stackTrace: Optional[str] = None
    errorCode: Optional[str] = None
    logLevel: Optional[str] = None
    occurredTime: Optional[datetime] = None
    impactedHostCount: int = 0
    repeatCount: int = 0


class IncidentResponse(BaseModel):
    id: int
    log_hash: str
    service_name: str
    summary: Optional[str] = None
    state: IncidentState
    retry_count: int
    impacted_host_count: int
    repeat_count: int
    occurred_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}