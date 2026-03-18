from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import AsyncSessionLocal


async def get_db() -> AsyncSession:
    """
    요청 1개당 세션 1개를 열고, 끝나면 자동으로 닫음.
    """
    async with AsyncSessionLocal() as session:
        yield session