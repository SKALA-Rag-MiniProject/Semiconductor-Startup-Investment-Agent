from typing import Any, Dict, List

from config import PROOF_RELEVANCE_THRESHOLD
from state import RetrievedDoc


def rewrite_query(question: str, company: str, attempt: int) -> str:
    base = f"{question} {company} chip architecture inference accelerator edge ai performance efficiency"
    if attempt == 1:
        return base
    return f"{base} deployment optimization benchmark limitation paper evidence"


def grade_retrieved_docs(question: str, company: str, docs: List[RetrievedDoc]) -> Dict[str, Any]:
    if not docs:
        return {"is_relevant": False, "score": 0.0, "reason": "검색된 문서가 없음"}

    company_hit_count = sum(1 for doc in docs if doc.get("company") == company)
    avg_score = sum(doc.get("score", 0.0) for doc in docs) / len(docs)
    blob = " ".join(doc.get("text", "") for doc in docs).lower()
    question_tokens = [token.lower() for token in question.replace(",", " ").split() if len(token) > 2]
    overlap = sum(1 for token in question_tokens if token in blob)

    relevance_score = 0.0
    relevance_score += min(company_hit_count / max(len(docs), 1), 1.0) * 0.5
    relevance_score += min(avg_score, 1.0) * 0.3
    relevance_score += min(overlap / max(len(question_tokens), 1), 1.0) * 0.2
    relevance_score = round(relevance_score, 2)

    is_relevant = relevance_score >= PROOF_RELEVANCE_THRESHOLD
    return {
        "is_relevant": is_relevant,
        "score": relevance_score,
        "reason": "문서 관련성 통과" if is_relevant else "문서 관련성이 낮아 재검색 필요",
    }
