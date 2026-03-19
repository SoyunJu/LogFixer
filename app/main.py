import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.exceptions import LogFixerException, logfixer_exception_handler
from app.core.logging import setup_logging
from app.db.session import create_tables

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("LogFixer 시작 중... (env=%s)", settings.APP_ENV)
    await create_tables()
    logger.info("DB 테이블 준비 완료")

    # Qdrant 컬렉션 초기화
    from app.vectordb.store import init_collections
    await init_collections()
    logger.info("Qdrant 컬렉션 준비 완료")

    yield

    logger.info("LogFixer 종료")


app = FastAPI(
    title="LogFixer",
    description="LC 연동 장애 자동 분석/해결 에이전트",
    version="0.1.0",
    lifespan=lifespan,
)

# 전역 예외 핸들러
app.add_exception_handler(LogFixerException, logfixer_exception_handler)

# ---- 라우터 -----------------------
from app.api.incident import router as incident_router
app.include_router(incident_router, prefix="/api")

@app.get("/health")
async def health_check():
    return {"status": "ok", "env": settings.APP_ENV}


# --- Slack ------------------------
from app.api import incident as incident_api
from app.api import slack_action as slack_api

app.include_router(incident_api.router, prefix="/api")
app.include_router(slack_api.router, prefix="/api")