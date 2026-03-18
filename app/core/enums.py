from enum import Enum


class IncidentState(str, Enum):
    """
    str 상속 -> JSON 문자열 변환.
    """
    RECEIVED = "RECEIVED"
    ANALYZING = "ANALYZING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    EXECUTING = "EXECUTING"
    RESOLVED = "RESOLVED"
    ROLLING_BACK = "ROLLING_BACK"
    ESCALATED = "ESCALATED"