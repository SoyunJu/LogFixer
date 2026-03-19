
import logging

from app.schemas.analysis import AnalysisResult

logger = logging.getLogger(__name__)

# 신뢰도가 0.4 미만 -> 재분석 or ESCALATED ##################### env
MIN_CONFIDENCE = 0.4

# allow action_type List ##################### env
VALID_ACTION_TYPES = {"RESTART", "EDIT_CONFIG", "DEL_DISK", "CLEAR_MEMORY"}


def validate(result: AnalysisResult) -> tuple[bool, list[str]]:
    issues = []

    # 1) 신뢰도 체크
    if result.confidence < MIN_CONFIDENCE:
        issues.append(
            f"신뢰도 너무 낮음: {result.confidence:.2f} (최소 {MIN_CONFIDENCE})"
        )

    # 2) 해결법 존재 여부
    if not result.solutions:
        issues.append("해결법 후보가 없음")

    # 3) action_type 유효성
    for sol in result.solutions:
        if sol.action_type not in VALID_ACTION_TYPES:
            issues.append(
                f"rank={sol.rank} action_type 유효하지 않음: {sol.action_type}"
            )

    # 4) EDIT_CONFIG 면 config_key/value 필수
    for sol in result.solutions:
        if sol.action_type == "EDIT_CONFIG":
            if not sol.config_key or not sol.config_value:
                issues.append(
                    f"rank={sol.rank} EDIT_CONFIG인데 config_key/value 없음"
                )

    if issues:
        logger.warning("[Validator] 검증 실패 logHash=%s issues=%s", result.log_hash, issues)
        return False, issues

    logger.info("[Validator] 검증 통과 logHash=%s", result.log_hash)
    return True, []