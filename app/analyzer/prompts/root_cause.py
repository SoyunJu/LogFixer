

def build_root_cause_prompt(
        service_name: str,
        summary: str,
        stack_trace: str | None,
        rag_context: list[dict],
) -> str:

    # RAG Doc -> Text
    if rag_context:
        context_text = ""
        for i, doc in enumerate(rag_context, start=1):
            context_text += f"""
[참고 문서 {i}]
제목: {doc.get('title', '')}
내용: {doc.get('content', '')[:300]}
해결법: {doc.get('addendum', '')[:300]}
출처: {doc.get('source', '')} (RRF 점수: {doc.get('rrf_score', 0):.4f})
"""
    else:
        context_text = "참고할 유사 사례 없음."

    stack_text = stack_trace or "stacktrace 없음"

    return f"""당신은 장애 원인을 분석하는 전문가입니다.

## 장애 정보
- 서비스명: {service_name}
- 에러 요약: {summary}
- Stacktrace:
{stack_text[:1000]}

## 유사 사례 (RAG 검색 결과)
{context_text}

## 지시사항
위 정보를 바탕으로 장애의 근본 원인을 한국어로 간결하게 분석하세요.
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "root_cause": "원인을 2~3문장으로 설명",
  "confidence": 0.85
}}"""