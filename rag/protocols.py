from __future__ import annotations

from typing import Any, Dict, List, Protocol

from state import RetrievedDoc


class PaperRetriever(Protocol):
    def search(self, company: str, query: str, top_k: int = 5) -> List[RetrievedDoc]:
        ...


class AnalysisModel(Protocol):
    def summarize(self, task: str, company: str, docs: List[RetrievedDoc], question: str) -> Dict[str, Any]:
        ...
