import logging

from app.rag.embedder import embed_incident
from app.rag.kb_search import bm25_search
from app.vectordb.store import search_error_patterns, search_kb_articles

logger = logging.getLogger(__name__)

# RRF 공식 상수 (보통 60 고정)
RRF_K = 60


############# RRF 계산 > rank 1 / (k + rank ) ############
def _rrf_score(rank: int) -> float:
    return 1.0 / (RRF_K + rank)


def _fuse(
        bm25_results: list[dict],
        knn_kb_results: list,
        knn_pattern_results: list,
        top_k: int,
) -> list[dict]:

    ########## Keyword , KbArticle, Pattern > RRF 합산 > top_k Response ###############

    scores: dict[str, float] = {}   # key: logHash, value: RRF 합산 점수
    meta: dict[str, dict] = {}      # key: logHash, value: 문서 메타 정보

    # BM25 결과 처리 (keyword)
    for rank, doc in enumerate(bm25_results, start=1):
        key = doc.get("logHash") or doc.get("kbArticleId", "")
        if not key:
            continue
        scores[key] = scores.get(key, 0.0) + _rrf_score(rank)
        meta[key] = {
            "logHash": doc.get("logHash", ""),
            "kbArticleId": doc.get("kbArticleId", ""),
            "title": doc.get("title", ""),
            "content": doc.get("content", ""),
            "source": "bm25",
        }

    # Qdrant KB 결과 처리
    for rank, point in enumerate(knn_kb_results, start=1):
        payload = point.payload or {}
        key = payload.get("logHash") or payload.get("kbArticleId", "")
        if not key:
            continue
        scores[key] = scores.get(key, 0.0) + _rrf_score(rank)
        if key not in meta:
            meta[key] = {
                "logHash": payload.get("logHash", ""),
                "kbArticleId": payload.get("kbArticleId", ""),
                "title": payload.get("title", ""),
                "content": payload.get("content", ""),
                "source": "knn_kb",
            }

    # Qdrant 결과 처리
    for rank, point in enumerate(knn_pattern_results, start=1):
        payload = point.payload or {}
        key = payload.get("patternId", "")
        if not key:
            continue
        scores[key] = scores.get(key, 0.0) + _rrf_score(rank)
        if key not in meta:
            meta[key] = {
                "logHash": "",
                "kbArticleId": "",
                "title": payload.get("errorType", ""),
                "content": payload.get("stacktraceSummary", ""),
                "source": "knn_pattern",
            }

    # RRF Rank desc
    sorted_keys = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)

    results = []
    for key in sorted_keys[:top_k]:
        doc = meta[key].copy()
        doc["rrf_score"] = round(scores[key], 6)
        results.append(doc)

    return results

#################### Main Method #####################
async def retrieve(
        summary: str,
        stack_trace: str | None,
        top_k: int = 5,
) -> list[dict]:

    # ######### (1) text embedding
    # ######### (2) BM25(ES)
    # ######### (3) kNN ( Qdrant -> kb_articles, error_patterns)
    # ######### # RRF sumUp
    # ######### # top_k Res (loghash, KbArticleId, title, content, source 1-3, rrf_score)

    # 1) Embedding
    vector = await embed_incident(summary, stack_trace)

    # 2-3) 3 검색 병렬 실행
    import asyncio
    bm25_results, knn_kb_results, knn_pattern_results = await asyncio.gather(
        bm25_search(query=summary, top_k=top_k * 2),       # 2배 검색
        search_kb_articles(vector=vector, top_k=top_k * 2),
        search_error_patterns(vector=vector, top_k=top_k * 2),
    )

    logger.info(
        "[RAG] 검색 완료 bm25=%d knn_kb=%d knn_pattern=%d",
        len(bm25_results), len(knn_kb_results), len(knn_pattern_results),
    )

    # 4) RRF reRanking
    fused = _fuse(bm25_results, knn_kb_results, knn_pattern_results, top_k)

    logger.info("[RAG] RRF 재랭킹 완료 → 상위 %d건 반환", len(fused))
    return fused