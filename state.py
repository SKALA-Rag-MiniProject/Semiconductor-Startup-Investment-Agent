from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


DecisionType = Literal["invest", "hold", "unknown"]


class RetrievedDoc(TypedDict, total=False):
    company: str
    title: str
    chunk_id: str
    text: str
    score: float
    source: str
    metadata: Dict[str, Any]


class ScorecardItem(TypedDict, total=False):
    """스코어카드 개별 항목 (보고서 표 렌더링용)."""
    category: str
    weight: float
    raw_score: int
    weighted_score: float
    judgement_label: str          # 우수|양호|보통|미흡|열악
    judgement_color: str          # green|blue|yellow|orange|red
    reason: str
    evidence: List[str]           # 이 점수의 근거 출처 목록


class HeadlineMetric(TypedDict, total=False):
    label: str
    value: str


class RiskFactor(TypedDict, total=False):
    level: str          # HIGH | MED | LOW
    title: str
    detail: str
    mitigation: str


class CompanyEvaluation(TypedDict, total=False):
    company_id: str
    company_name: str
    retrieval_query: str
    retrieval_attempts: int
    retrieval_status: str
    retrieved_docs: List[RetrievedDoc]
    proof_status: str
    proof_notes: List[str]

    # ── 선행 에이전트 결과 ──
    tech_summary: str
    tech_score: float
    tech_rubric: Dict[str, Any]
    market_summary: str
    market_score: float
    competitor_summary: str
    competitor_score: float
    risk_summary: str
    risk_score: float

    # ── 투자 판단 에이전트 출력 (Scorecard Valuation Method) ──
    scorecard: List[ScorecardItem]
    total_score: float
    investment_decision: DecisionType
    grade: str                          # A / B / C / D / 보류
    badge_label: str                    # INVEST / HOLD
    badge_subtitle: str                 # 투자 추천 / 보류
    decision_summary: str               # SUMMARY용 한 줄 판단
    investment_highlights: List[str]    # 최종 투자의견 박스 핵심 근거
    decision_reason_detailed: str       # 상세 판단 근거 2~4문장
    headline_metrics: List[HeadlineMetric]
    risk_factors: List[RiskFactor]
    decision_confidence: str            # high / medium / low
    decision_status: str                # SUCCESS / NEED_MORE_EVIDENCE
    missing_inputs: List[str]
    needs_human_review: bool

    # ── 하위 호환 (레거시) ──
    decision: str
    decision_reason: str


class AgentState(TypedDict, total=False):
    question: str
    target_companies: List[str]
    current_company_id: Optional[str]
    companies: Dict[str, CompanyEvaluation]
    current_index: int
    total_companies: int
    should_finalize: bool
    stop_reason: str
    log: List[str]
    final_report: str           # 최종 보고서 (마크다운)
    answer: str                 # 보고서 생성 에이전트 최종 출력


def create_initial_state(question: str, target_companies: List[str]) -> AgentState:
    return {
        "question": question,
        "target_companies": target_companies,
        "current_company_id": None,
        "companies": {},
        "current_index": 0,
        "total_companies": len(target_companies),
        "should_finalize": False,
        "stop_reason": "",
        "log": [],
        "final_report": "",
        "answer": "",
    }


def add_log(state: AgentState, node: str, message: str) -> None:
    state["log"].append(f"[{node}] {message}")


def ensure_company_slot(state: AgentState, company_id: str) -> CompanyEvaluation:
    companies = state["companies"]
    if company_id not in companies:
        companies[company_id] = {
            "company_id": company_id,
            "company_name": company_id,
            "retrieval_query": "",
            "retrieval_attempts": 0,
            "retrieval_status": "pending",
            "retrieved_docs": [],
            "proof_status": "unverified",
            "proof_notes": [],
            "tech_summary": "",
            "tech_score": 0.0,
            "tech_rubric": {},
            "market_summary": "",
            "market_score": 0.0,
            "competitor_summary": "",
            "competitor_score": 0.0,
            "risk_summary": "",
            "risk_score": 0.0,
            # ── 투자 판단 신규 필드 ──
            "scorecard": [],
            "total_score": 0.0,
            "investment_decision": "unknown",
            "grade": "",
            "badge_label": "",
            "badge_subtitle": "",
            "decision_summary": "",
            "investment_highlights": [],
            "decision_reason_detailed": "",
            "headline_metrics": [],
            "risk_factors": [],
            "decision_confidence": "low",
            "decision_status": "",
            "missing_inputs": [],
            "needs_human_review": False,
            # ── 레거시 ──
            "decision": "unknown",
            "decision_reason": "",
        }
    return companies[company_id]


def get_current_company(state: AgentState) -> CompanyEvaluation:
    company_id = state["current_company_id"]
    if company_id is None:
        raise ValueError("current_company_id is not set")
    return state["companies"][company_id]
