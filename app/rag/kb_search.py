import logging

from elasticsearch import AsyncElasticsearch

from app.core.config import settings

logger = logging.getLogger(__name__)

# ES client
_es_client: AsyncElasticsearch | None = None

ES_INDEX = "kb_articles"


    # 싱글턴 -----------------------------------------------------------
def get_es_client() -> AsyncElasticsearch:
    global _es_client
    if _es_client is None:
        _es_client = AsyncElasticsearch(hosts=[settings.ES_HOST])
    return _es_client

    # BM25 Keyword Search >>>> summary + stackTrace + title
async def bm25_search(
        query: str,
        top_k: int = 5,
) -> list[dict]:
    """
    ################# Response ########### :
    [
      {
        "kbArticleId": "...",
        "logHash": "...",
        "title": "...",
        "content": "...",
        "score": 1.23,
      },
      ...
    ]
    """
    es = get_es_client()

    # ES 인덱스가 없으면 빈 결과 반환 (LC가 아직 데이터 없을 수 있음)
    index_exists = await es.indices.exists(index=ES_INDEX)
    if not index_exists:
        logger.warning("[ES] 인덱스 없음: %s → BM25 결과 없음", ES_INDEX)
        return []

    body = {
        "size": top_k,
        "query": {
            "multi_match": {
                "query": query,
                "fields": ["title^2", "content", "addendum^1.5", "stacktraceSummary"],
                # title 가중치 2배, content/stacktrace는 1배, addendum 1.5배
            }
        },
    }

    response = await es.search(index=ES_INDEX, body=body)
    hits = response["hits"]["hits"]

    results = []
    for hit in hits:
        src = hit["_source"]
        results.append({
            "kbArticleId": src.get("kbArticleId") or hit["_id"],
            "logHash": src.get("logHash", ""),
            "title": src.get("title", ""),
            "content": src.get("content", ""),
            "score": hit["_score"],
        })

    logger.debug("[ES][BM25] 검색 결과 %d건 query='%s'", len(results), query[:50])
    return results