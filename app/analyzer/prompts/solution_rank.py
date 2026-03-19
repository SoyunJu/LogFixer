

def build_solution_rank_prompt(
        service_name: str,
        root_cause: str,
        rag_context: list[dict],
) -> str:

    if rag_context:
        context_text = ""
        for i, doc in enumerate(rag_context, start=1):
            context_text += f"""
[참고 문서 {i}]
제목: {doc.get('title', '')}
해결법: {doc.get('addendum', '')[:400]}
"""
    else:
        context_text = "참고할 유사 사례 없음."

    return f"""당신은 장애 해결법을 제시하는 전문가입니다.

## 장애 정보
- 서비스명: {service_name}
- 원인 분석: {root_cause}

## 유사 사례의 해결법 (RAG 검색 결과)
{context_text}

## 지시사항
위 정보를 바탕으로 실행 가능한 해결법을 우선순위 순으로 최대 3개 제안하세요.
action_type은 반드시 RESTART / EDIT_CONFIG / DEL_DISK / CLEAR_MEMORY 중 하나여야 합니다.
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 절대 포함하지 마세요.

{{
  "solutions": [
    {{
      "rank": 1,
      "action_type": "RESTART",
      "description": "서비스 재시작으로 메모리 해제",
      "target": "service-name",
      "config_key": null,
      "config_value": null,
      "confidence": 0.9
    }},
    {{
      "rank": 2,
      "action_type": "EDIT_CONFIG",
      "description": "heap 설정을 4G로 증가",
      "target": "/etc/app.conf",
      "config_key": "heap",
      "config_value": "4g",
      "confidence": 0.75
    }}
  ]
}}"""