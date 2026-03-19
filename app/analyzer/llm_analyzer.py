
import json
import logging

from openai import AsyncOpenAI

from app.core.config import settings
from app.analyzer.prompts.root_cause import build_root_cause_prompt
from app.analyzer.prompts.solution_rank import build_solution_rank_prompt
from app.schemas.analysis import AnalysisResult, SolutionCandidate
from app.rag.retriever import retrieve

logger = logging.getLogger(__name__)

_client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

# ######## Model ####################
LLM_MODEL = "gpt-4o-mini"


async def _call_llm(prompt: str) -> str:

    response = await _client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},            # JSON만 반환 강제
        temperature=0.2,                                # 낮을수록 일관된 답변 (분석용)
    )
    return response.choices[0].message.content


async def analyze(
        log_hash: str,
        service_name: str,
        summary: str,
        stack_trace: str | None,
        top_k: int = 5,
) -> AnalysisResult:

    # 1) RAG ---------------------------------------------------
    logger.info("[Analyzer] RAG 검색 시작 logHash=%s", log_hash)
    rag_context = await retrieve(summary=summary, stack_trace=stack_trace, top_k=top_k)

    # 2) root cause ---------------------------------------------------
    logger.info("[Analyzer] 원인 분석 LLM 호출 logHash=%s", log_hash)
    root_cause_prompt = build_root_cause_prompt(
        service_name=service_name,
        summary=summary,
        stack_trace=stack_trace,
        rag_context=rag_context,
    )
    root_cause_raw = await _call_llm(root_cause_prompt)

    try:
        root_cause_json = json.loads(root_cause_raw)
        root_cause = root_cause_json.get("root_cause", "원인 분석 실패")
        confidence = float(root_cause_json.get("confidence", 0.5))
    except (json.JSONDecodeError, ValueError):
        logger.warning("[Analyzer] 원인 분석 JSON 파싱 실패 raw=%s", root_cause_raw[:200])
        root_cause = "원인 분석 실패 (LLM 응답 파싱 오류)"
        confidence = 0.0

    # 3) ranking ---------------------------------------------------
    logger.info("[Analyzer] 해결법 순위 LLM 호출 logHash=%s", log_hash)
    solution_prompt = build_solution_rank_prompt(
        service_name=service_name,
        root_cause=root_cause,
        rag_context=rag_context,
    )
    solution_raw = await _call_llm(solution_prompt)

    try:
        solution_json = json.loads(solution_raw)
        solutions = [
            SolutionCandidate(**s)
            for s in solution_json.get("solutions", [])
        ]
    except (json.JSONDecodeError, ValueError, TypeError):
        logger.warning("[Analyzer] 해결법 JSON 파싱 실패 raw=%s", solution_raw[:200])
        solutions = []

    # 4) sum up ---------------------------------------------------
    rag_sources = [
        doc.get("kbArticleId") or doc.get("logHash", "unknown")
        for doc in rag_context
    ]

    result = AnalysisResult(
        log_hash=log_hash,
        root_cause=root_cause,
        confidence=confidence,
        solutions=solutions,
        rag_sources=rag_sources,
        raw_llm_response=f"root_cause: {root_cause_raw}\nsolutions: {solution_raw}",
    )

    logger.info(
        "[Analyzer] 분석 완료 logHash=%s confidence=%.2f solutions=%d",
        log_hash, confidence, len(solutions),
    )
    return result