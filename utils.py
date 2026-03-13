from typing import Dict, List, Tuple

from config import (
    GRADE_DEFAULT,
    GRADE_THRESHOLDS,
    JUDGEMENT_DEFAULT,
    JUDGEMENT_THRESHOLDS,
    SCORECARD_WEIGHTS,
)


def weighted_total(scorecard_items: List[Dict]) -> float:
    """scorecard list[dict] 의 weighted_score 합계를 반환한다."""
    return round(sum(item["weighted_score"] for item in scorecard_items), 1)


def score_to_grade(total_score: float) -> str:
    """종합 점수로 등급 결정."""
    for threshold, grade in GRADE_THRESHOLDS:
        if total_score >= threshold:
            return grade
    return GRADE_DEFAULT


def score_to_judgement(raw_score: int) -> Tuple[str, str]:
    """개별 항목 점수 → (label, color)."""
    for threshold, label, color in JUDGEMENT_THRESHOLDS:
        if raw_score >= threshold:
            return label, color
    return JUDGEMENT_DEFAULT


def make_scorecard_item(
    category: str,
    raw_score: int,
    reason: str,
    evidence: List[str] | None = None,
) -> Dict:
    """스코어카드 한 행을 생성한다."""
    weight = SCORECARD_WEIGHTS[category]
    weighted_score = round(raw_score * weight, 1)
    label, color = score_to_judgement(raw_score)
    return {
        "category": category,
        "weight": weight,
        "raw_score": raw_score,
        "weighted_score": weighted_score,
        "judgement_label": label,
        "judgement_color": color,
        "reason": reason,
        "evidence": evidence or [],
    }
