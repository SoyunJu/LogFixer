from qdrant_client import AsyncQdrantClient

from app.core.config import settings

# Qdrant client
_qdrant_client: AsyncQdrantClient | None = None


    # 싱글턴 패턴 / 클라이언트 1개만 유지 / new는 생성, 이후 재사용 -------------------------------
def get_qdrant_client() -> AsyncQdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
        )
    return _qdrant_client