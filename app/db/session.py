from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# 비동기 엔진 생성
# echo=True 면 실행되는 SQL이 콘솔에 출력됨 (개발할 때 유용)
engine = create_async_engine(
    settings.db_url,
    echo=(settings.APP_ENV == "development"),
    pool_pre_ping=True,   # DB 연결이 끊겼을 때 자동 재연결 시도
)

# 세션 팩토리
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 후에도 객체 속성을 다시 읽을 수 있게 함
)


# dev -> auto create
async def create_tables() -> None:
    from app.db.models import Base
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)