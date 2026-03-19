
import json
import logging
from datetime import datetime
from pytz import timezone

from app.db.models import LfIncident

logger = logging.getLogger(__name__)

    # Korea Time conf
kst = timezone('Asia/Seoul')
    # UTC -> KST
now_kst = datetime.now(kst)

    # FOR : LogCollector KbArticle_addendum save , Create content(Text)
def generate_addendum_content(incident: LfIncident) -> str:

    solutions_raw = incident.solutions_json or "[]"
    solutions = json.loads(solutions_raw)

    # action_list -> text
    actions_text = ""
    for sol in solutions:
        actions_text += (
            f"\n- [{sol.get('action_type')}] {sol.get('description', '')}"
        )

    content = (
        f"[LogFixer Agent 실행 결과]\n"
        f"원인: {incident.root_cause or '분석 결과 없음'}\n"
        f"신뢰도: {int((incident.confidence or 0) * 100)}%\n"
        f"실행 내역:{actions_text}\n"
        f"해결 시각: {now_kst.strftime('%Y-%m-%d %H:%M:%S')} KST"
    )
    return content




def generate_actions_taken(incident: LfIncident) -> list[str]:

    solutions_raw = incident.solutions_json or "[]"
    solutions = json.loads(solutions_raw)

    actions = []
    for sol in solutions:
        action_type = sol.get("action_type", "")
        description = sol.get("description", "")
        target = sol.get("target", "")
        if target:
            actions.append(f"{action_type}: {description} ({target})")
        else:
            actions.append(f"{action_type}: {description}")

    return actions