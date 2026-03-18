from datetime import datetime

from sqlalchemy import (
    BigInteger, DateTime, Enum, Integer, String, Text, func
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.core.enums import IncidentState


class Base(DeclarativeBase):
    pass


# LC Incident save table ***
class LfIncident(Base):
    __tablename__ = "lf_incident"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # LC 연동 식별자
    log_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=True)        # 에러 요약
    stack_trace: Mapped[str] = mapped_column(Text, nullable=True)
    error_code: Mapped[str] = mapped_column(String(100), nullable=True)
    log_level: Mapped[str] = mapped_column(String(20), nullable=True)

    impacted_host_count: Mapped[int] = mapped_column(Integer, default=0)
    repeat_count: Mapped[int] = mapped_column(Integer, default=0)

    # Status (LC 의 Incident 가 SoT)
    state: Mapped[IncidentState] = mapped_column(
        Enum(IncidentState),
        default=IncidentState.RECEIVED,
        nullable=False,
    )

    # 재시도 횟수 (ROLLING_BACK → RECEIVED 반복 시 카운트)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)

    # Slack 메시지 추적용 (알림 보낸 메시지 ID 저장)
    slack_ts: Mapped[str] = mapped_column(String(50), nullable=True)

    # 시간 정보
    occurred_at: Mapped[datetime] = mapped_column(DateTime, nullable=True)   # LC data
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())