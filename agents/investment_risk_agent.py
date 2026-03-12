from config import (
    COMPETITOR_SCORE_THRESHOLD,
    MARKET_SCORE_THRESHOLD,
    RISK_BASE_SCORE,
    RISK_COMPETITOR_PENALTY,
    RISK_MARKET_PENALTY,
    RISK_PROOF_PENALTY,
    RISK_TECH_PENALTY,
    TECH_SCORE_THRESHOLD,
)
from state import AgentState, add_log, get_current_company


def investment_risk_agent(state: AgentState) -> AgentState:
    company = get_current_company(state)

    risks = []
    summary_parts = []
    risk_score = RISK_BASE_SCORE

    if company["proof_status"] != "verified":
        risks.append("검색 근거의 관련성 검증이 충분하지 않음")
        summary_parts.append("근거 검증이 충분하지 않아 판단 신뢰도에 제약이 있음.")
        risk_score += RISK_PROOF_PENALTY

    if company["market_score"] < MARKET_SCORE_THRESHOLD:
        risks.append("시장 채택 속도가 예상보다 느릴 수 있음")
        summary_parts.append("시장 확산 및 고객 전환 속도가 핵심 리스크임.")
        risk_score += RISK_MARKET_PENALTY

    if company["competitor_score"] < COMPETITOR_SCORE_THRESHOLD:
        risks.append("경쟁 강도와 상용화 장벽이 높음")
        summary_parts.append("경쟁 환경 측면의 방어력이 충분한지 추가 검토 필요.")
        risk_score += RISK_COMPETITOR_PENALTY

    if company["tech_score"] < TECH_SCORE_THRESHOLD:
        risks.append("기술 차별성 근거가 더 필요함")
        summary_parts.append("기술 우위의 지속 가능성 검증이 더 필요함.")
        risk_score += RISK_TECH_PENALTY

    if not risks:
        risks.append("현재 근거 기준 중대한 리스크는 제한적임")
        summary_parts.append("현재 확보된 자료 기준에서는 치명적 리스크가 두드러지지 않음.")

    company["risk_factors"] = risks
    company["risk_summary"] = " ".join(summary_parts)
    company["risk_score"] = round(min(risk_score, 1.0), 2)
    add_log(state, "investment_risk", f"{company['company_name']} risk_score={company['risk_score']}")
    return state
