from typing import Optional
from pydantic import BaseModel


# ########## 해결법 순위 1개
class SolutionCandidate(BaseModel):
    rank: int
    action_type: str                 # RESTART / EDIT_CONFIG / DEL_DISK / CLEAR_MEMORY
    description: str
    target: Optional[str] = None
    config_key: Optional[str] = None
    config_value: Optional[str] = None
    confidence: float                # 0.0 ~ 1.0

# ####### LLM 분석 결과
class AnalysisResult(BaseModel):
    log_hash: str
    root_cause: str                        # 원인
    confidence: float                      # 전체 신뢰도 0.0 ~ 1.0
    solutions: list[SolutionCandidate]     # 해결법 list (rank)
    rag_sources: list[str]                 # KbArticle, addendum
    raw_llm_response: Optional[str] = None  # 디버깅용 LLM 원본 res