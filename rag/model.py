from __future__ import annotations

from typing import Any, Dict, List

from rag.scoring import summarize_technical_capability
from state import RetrievedDoc


class ProjectAnalysisModel:
    def summarize(self, task: str, company: str, docs: List[RetrievedDoc], question: str) -> Dict[str, Any]:
        blob = " ".join(doc.get("text", "") for doc in docs).lower()
        if task == "technology":
            return summarize_technical_capability(company=company, docs=docs)
        if task == "market":
            score = 0.60
            summary = ["기술 문서 기반이므로 시장성 평가는 보수적으로 해석합니다."]
            if "deployment" in blob or "customer" in blob or "product" in blob:
                score += 0.08
                summary.append("상용 배포 및 고객 전환 가능성을 시사하는 표현이 있습니다.")
            if "edge" in blob or "datacenter" in blob or "server" in blob:
                score += 0.05
                summary.append("적용 시장 범위가 일정 수준 확인됩니다.")
            if "benchmark" not in blob and "customer" not in blob:
                score -= 0.07
                summary.append("상용 확산을 직접 입증하는 자료는 제한적입니다.")
            return {"summary": " ".join(summary), "score": round(max(0.0, min(score, 1.0)), 2)}
        if task == "competition":
            score = 0.52
            summary: List[str] = []
            if "novel" in blob or "architecture" in blob or "low-power" in blob:
                score += 0.10
                summary.append("기술 차별화 포인트가 경쟁 우위로 연결될 여지가 있습니다.")
            if "deployment" in blob or "sdk" in blob or "customer" in blob:
                score += 0.05
                summary.append("상용화 실행력이 경쟁 비교에서 중요하게 작용할 수 있습니다.")
            if "benchmark" not in blob:
                score -= 0.05
                summary.append("객관적 비교 지표가 부족해 경쟁우위 판단은 보수적으로 봐야 합니다.")
            if not summary:
                summary.append("경쟁 비교를 위해 추가 자료가 필요합니다.")
            return {"summary": " ".join(summary), "score": round(max(0.0, min(score, 1.0)), 2)}
        raise ValueError(f"Unsupported task: {task}")
