from __future__ import annotations

from typing import Any, Dict, List

from config import TECH_CRITERIA
from rag.embedder import compact_text
from state import RetrievedDoc


def score_criterion(evidences: List[RetrievedDoc], keywords: List[str]) -> int:
    text_blob = " ".join(row.get("text", "").lower() for row in evidences)
    keyword_hits = sum(1 for keyword in keywords if keyword in text_blob)
    similarity = sum(float(row.get("score", 0.0)) for row in evidences) / max(1, len(evidences))

    base = 1
    if keyword_hits >= 6:
        base = 5
    elif keyword_hits >= 4:
        base = 4
    elif keyword_hits >= 2:
        base = 3
    elif keyword_hits >= 1:
        base = 2

    if similarity > 0.70:
        base = min(5, base + 1)
    if similarity < 0.35:
        base = max(1, base - 1)
    return base


def summarize_technical_capability(company: str, docs: List[RetrievedDoc]) -> Dict[str, Any]:
    criteria_rows: Dict[str, Dict[str, Any]] = {}
    total = 0.0

    for criterion, cfg in TECH_CRITERIA.items():
        score = score_criterion(docs, cfg["keywords"])
        total += score
        evidence_lines = [
            f"{doc['source']}:{doc['metadata'].get('page', '?')} (sim={doc.get('score', 0.0):.4f}) {compact_text(doc.get('text', ''))[:150]}..."
            for doc in docs[:3]
        ]
        criteria_rows[criterion] = {
            "score": score,
            "question": cfg["question"],
            "evidence": evidence_lines,
        }

    avg_score_5 = round(total / max(len(TECH_CRITERIA), 1), 2)
    normalized_score = round(min(max(avg_score_5 / 5.0, 0.0), 1.0), 2)

    summary_parts: List[str] = []
    if criteria_rows["기술 독창성"]["score"] >= 4:
        summary_parts.append("구조적 차별성 근거가 비교적 명확합니다.")
    else:
        summary_parts.append("구조적 차별성은 추가 검증이 필요합니다.")
    if criteria_rows["구현 성숙도"]["score"] >= 4:
        summary_parts.append("실행 및 구현 성숙도 근거가 상대적으로 잘 드러납니다.")
    else:
        summary_parts.append("실칩, 제품, SDK, 데모 등 구현 성숙도 근거는 더 보강되어야 합니다.")
    if criteria_rows["효율성"]["score"] >= 4:
        summary_parts.append("성능 또는 효율 관련 근거가 비교적 충분합니다.")
    else:
        summary_parts.append("성능-전력-메모리 효율 증명은 추가 자료 확보가 필요합니다.")
    if criteria_rows["확장성 / 적용 가능성"]["score"] >= 4:
        summary_parts.append("적용 범위와 확장 가능성도 긍정적으로 해석됩니다.")
    else:
        summary_parts.append("적용 범위와 상용 확장성은 더 확인이 필요합니다.")

    return {
        "company": company,
        "summary": " ".join(summary_parts),
        "score": normalized_score,
        "avg_score_5": avg_score_5,
        "criteria": criteria_rows,
    }
