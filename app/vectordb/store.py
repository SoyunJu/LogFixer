import logging
from uuid import uuid4

from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from app.rag.embedder import EMBEDDING_DIM
from app.vectordb.client import get_qdrant_client

logger = logging.getLogger(__name__)

    # Doc Collection -------------------------------------------------------------------
COLLECTION_KB_ARTICLES = "kb_articles"      # LC meta data + addendums
COLLECTION_ERROR_PATTERNS = "error_patterns"
COLLECTION_SOLUTIONS = "solutions"


async def init_collections() -> None:
    client = get_qdrant_client()

    for name in [COLLECTION_KB_ARTICLES, COLLECTION_ERROR_PATTERNS, COLLECTION_SOLUTIONS]:
        exists = await client.collection_exists(name)
        if not exists:
            await client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,  # 코사인 유사도로 검색
                ),
            )
            logger.info("[Qdrant] 컬렉션 생성 완료: %s", name)
        else:
            logger.info("[Qdrant] 컬렉션 이미 존재: %s", name)


    # KbArticle -> Qdrant upsert
async def upsert_kb_article(
        kb_article_id: str,
        log_hash: str,
        title: str,
        content: str,
        vector: list[float],
        addendums: list[str] | None = None,
        resolved_count: int = 0,
) -> None:
    # before : content(statcktrace) + addendums , after : embedding

    addendums = addendums or []
    addendum_combined = "\n".join(addendums)    # content(statcktrace) + addendums

    client = get_qdrant_client()
    await client.upsert(
        collection_name=COLLECTION_KB_ARTICLES,
        points=[
            PointStruct(
                id=str(uuid4()),
                vector=vector,
                payload={
                    "kbArticleId": kb_article_id,
                    "logHash": log_hash,
                    "title": title,
                    "content": content,                      # stacktrace
                    "addendum": addendum_combined,           # addendums
                    "resolvedCount": resolved_count,
                },
            )
        ],
    )
    logger.info("[Qdrant][KB] upsert 완료 kbArticleId=%s addendumCount=%d", kb_article_id, len(addendums))


async def upsert_error_pattern(
        pattern_id: str,
        error_type: str,
        stacktrace_summary: str,
        vector: list[float],
        occurrence_count: int = 1,
) -> None:

    client = get_qdrant_client()
    await client.upsert(
        collection_name=COLLECTION_ERROR_PATTERNS,
        points=[
            PointStruct(
                id=str(uuid4()),
                vector=vector,
                payload={
                    "patternId": pattern_id,
                    "errorType": error_type,
                    "stacktraceSummary": stacktrace_summary,
                    "occurrenceCount": occurrence_count,
                },
            )
        ],
    )
    logger.info("[Qdrant][Pattern] upsert 완료 patternId=%s", pattern_id)


async def search_kb_articles(
        vector: list[float],
        top_k: int = 5,
) -> list[ScoredPoint]:

    client = get_qdrant_client()
    results = await client.search(
        collection_name=COLLECTION_KB_ARTICLES,
        query_vector=vector,
        limit=top_k,
        with_payload=True,
    )
    logger.debug("[Qdrant][KB] 검색 결과 %d건", len(results))
    return results


async def search_error_patterns(
        vector: list[float],
        top_k: int = 5,
) -> list[ScoredPoint]:

    client = get_qdrant_client()
    results = await client.search(
        collection_name=COLLECTION_ERROR_PATTERNS,
        query_vector=vector,
        limit=top_k,
        with_payload=True,
    )
    logger.debug("[Qdrant][Pattern] 검색 결과 %d건", len(results))
    return results