"""투자 판단 에이전트 (Scorecard Valuation Method — 반도체 스타트업 보정).

선행 에이전트(기술/시장/경쟁)의 점수·요약과 기업 프로필을 종합하여
6개 항목 스코어카드를 산출하고 invest / hold 결정을 내린다.
"""

from __future__ import annotations

from typing import List

from config import (
    EXECUTION_DOC_THRESHOLD,
    INVEST_THRESHOLD,
)
from state import AgentState, CompanyEvaluation, add_log, get_current_company
from utils import make_scorecard_item, score_to_grade, weighted_total


# ────────────────────────────────────────────────────────
# 내부 헬퍼
# ────────────────────────────────────────────────────────

def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> int:
    return int(max(lo, min(hi, round(value))))


def _score_founder_team(company: CompanyEvaluation) -> tuple[int, str]:
    """창업자/팀 점수: 기술 루브릭·문서 수·proof_status 기반 추정."""
    rubric = company.get("tech_rubric", {})
    rubric_scores = [row.get("score", 0) for row in rubric.values()] if rubric else []
    avg_rubric = sum(rubric_scores) / len(rubric_scores) if rubric_scores else 2.5

    doc_count = len(company.get("retrieved_docs", []))
    proof_ok = company.get("proof_status") == "verified"

    base = avg_rubric * 16  # 2.5 → 40, 4.0 → 64, 5.0 → 80
    if proof_ok:
        base += 8
    if doc_count >= EXECUTION_DOC_THRESHOLD:
        base += 5

    score = _clamp(base)
    reasons = []
    if score >= 75:
        reasons.append("기술 루브릭 및 문서 기반 실행력·전문성이 높게 평가됨")
    elif score >= 60:
        reasons.append("팀 전문성은 확인되나 추가 검증이 필요함")
    else:
        reasons.append("팀 정보가 제한적이어서 보수적으로 평가함")
    return score, reasons[0]


def _score_market(company: CompanyEvaluation) -> tuple[int, str]:
    """시장성: 선행 market_score (0~1) → 100점 척도."""
    raw = company.get("market_score", 0.0)
    score = _clamp(raw * 100)
    if score >= 80:
        reason = "시장 규모 및 성장 가능성이 높음"
    elif score >= 60:
        reason = "시장 기회는 존재하나 채택 속도의 보수적 해석 필요"
    else:
        reason = "시장성 근거가 부족하여 보수적 평가"
    return score, reason


def _score_product_tech(company: CompanyEvaluation) -> tuple[int, str]:
    """제품/기술력: 선행 tech_score (0~1) → 100점 척도."""
    raw = company.get("tech_score", 0.0)
    score = _clamp(raw * 100)
    if score >= 80:
        reason = "기술 독창성과 구현 가능성이 높음"
    elif score >= 60:
        reason = "기술적 차별성은 있으나 구현 성숙도 보강 필요"
    else:
        reason = "기술력 근거가 제한적"
    return score, reason


def _score_competitive_advantage(company: CompanyEvaluation) -> tuple[int, str]:
    """경쟁 우위: 선행 competitor_score (0~1) → 100점 척도."""
    raw = company.get("competitor_score", 0.0)
    score = _clamp(raw * 100)
    if score >= 70:
        reason = "진입장벽 또는 기술 차별화가 경쟁 우위로 작용"
    elif score >= 50:
        reason = "차별화 포인트는 있으나 객관적 비교 지표 부족"
    else:
        reason = "경쟁 우위 근거가 부족"
    return score, reason


def _score_track_record(company: CompanyEvaluation) -> tuple[int, str]:
    """실적: PoC/문서/증명 상태 기반 추정."""
    doc_count = len(company.get("retrieved_docs", []))
    proof_ok = company.get("proof_status") == "verified"
    tech_rubric = company.get("tech_rubric", {})
    maturity = tech_rubric.get("구현 성숙도", {}).get("score", 2)

    base = maturity * 14  # 2→28, 3→42, 4→56, 5→70
    if proof_ok:
        base += 10
    if doc_count >= 3:
        base += 5

    score = _clamp(base)
    if score >= 70:
        reason = "PoC, 고객 검증 등 구체적 실적이 확인됨"
    elif score >= 50:
        reason = "일부 실적 근거가 있으나 상용 전환 확인 필요"
    else:
        reason = "실적 정보가 제한적이어서 보수적 평가"
    return score, reason


def _score_investment_terms(company: CompanyEvaluation) -> tuple[int, str]:
    """투자조건: 현재 입력에 기업가치/지분율 데이터가 없으므로 보수적 고정값."""
    score = 55
    reason = "투자조건 관련 상세 정보가 부족하여 보수적으로 평가"
    return score, reason


def _build_risk_factors(company: CompanyEvaluation) -> list[dict]:
    """리스크 요인을 HIGH/MED/LOW 구조체로 생성."""
    factors: list[dict] = []

    # 시장 채택 리스크
    if company.get("market_score", 0.0) < 0.70:
        factors.append({
            "level": "HIGH",
            "title": "시장 채택 속도 불확실성",
            "detail": "시장 점수가 보수적으로 평가되어 상용 채택 속도가 예상보다 느릴 수 있음",
            "mitigation": "PoC 확대 및 전략적 고객 확보로 채택 가속 필요",
        })

    # 기술 차별성 지속 리스크
    if company.get("tech_score", 0.0) < 0.80:
        factors.append({
            "level": "MED",
            "title": "기술 차별성 지속 가능성",
            "detail": "기술 우위가 경쟁사 추격 시 유지 가능한지 추가 검증 필요",
            "mitigation": "지속적 R&D 투자 및 특허 포트폴리오 강화",
        })

    # 경쟁 심화 리스크
    if company.get("competitor_score", 0.0) < 0.60:
        factors.append({
            "level": "HIGH",
            "title": "글로벌 경쟁 심화",
            "detail": "대형 경쟁사의 시장 진입으로 경쟁 강도가 높아질 수 있음",
            "mitigation": "니치 시장 집중 또는 전략 파트너십 확보",
        })

    # 자본 집약 리스크
    factors.append({
        "level": "MED",
        "title": "자본 집약적 구조",
        "detail": "반도체 스타트업 특성상 tape-out 및 양산 시 추가 자금 소요 가능",
        "mitigation": "전략 투자자 확보 및 후속 라운드 계획 확인 필요",
    })

    # 투자조건 정보 부족
    factors.append({
        "level": "LOW",
        "title": "투자조건 정보 제한",
        "detail": "기업가치, 지분율 등 상세 투자 조건 정보가 부족",
        "mitigation": "실사 단계에서 상세 조건 확인 필요",
    })

    # severity 순 정렬
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    factors.sort(key=lambda f: order.get(f["level"], 9))
    return factors


def _build_headline_metrics(company: CompanyEvaluation) -> list[dict]:
    """headline_metrics: 현재 입력에서 추출 가능한 항목만 생성."""
    metrics: list[dict] = []
    # 현재 파이프라인에 TAM/CAGR/누적투자/기업가치 데이터가 없으므로
    # 빈 리스트를 반환한다. 실제 startup_profile에 값이 있으면 여기서 추출.
    return metrics


def _check_missing_inputs(company: CompanyEvaluation) -> list[str]:
    """입력 완전성 검사: 비어 있거나 100자 미만인 필드 기록."""
    missing = []
    for field in ("tech_summary", "market_summary", "competitor_summary"):
        val = company.get(field, "")
        if not val or len(val) < 100:
            missing.append(field)
    return missing


# ────────────────────────────────────────────────────────
# 메인 에이전트
# ────────────────────────────────────────────────────────

def investment_decision_agent(state: AgentState) -> AgentState:
    """Scorecard Valuation Method 기반 투자 판단을 수행한다."""
    company = get_current_company(state)

    # ── 1) 6개 항목 스코어 산출 ──
    items = []
    founder_score, founder_reason = _score_founder_team(company)
    items.append(make_scorecard_item("창업자/팀", founder_score, founder_reason))

    market_score, market_reason = _score_market(company)
    items.append(make_scorecard_item("시장성", market_score, market_reason))

    tech_score, tech_reason = _score_product_tech(company)
    items.append(make_scorecard_item("제품/기술력", tech_score, tech_reason))

    comp_score, comp_reason = _score_competitive_advantage(company)
    items.append(make_scorecard_item("경쟁 우위", comp_score, comp_reason))

    track_score, track_reason = _score_track_record(company)
    items.append(make_scorecard_item("실적", track_score, track_reason))

    terms_score, terms_reason = _score_investment_terms(company)
    items.append(make_scorecard_item("투자조건", terms_score, terms_reason))

    # ── 2) 종합 점수 ──
    total = weighted_total(items)
    grade = score_to_grade(total)

    # ── 3) 투자 결정 ──
    if total >= INVEST_THRESHOLD:
        decision = "invest"
        badge_label = "INVEST"
        badge_subtitle = "투자 추천"
    else:
        decision = "hold"
        badge_label = "HOLD"
        badge_subtitle = "보류"

    # ── 4) 판단 근거 ──
    highlights: List[str] = []
    if tech_score >= 75:
        highlights.append("기술 경쟁력이 비교적 뚜렷함")
    else:
        highlights.append("기술 우위 주장은 있으나 추가 증명 필요")
    if market_score >= 68:
        highlights.append("시장 수요 측면의 기회 존재")
    else:
        highlights.append("시장성은 있으나 채택 속도의 보수적 해석 필요")
    if comp_score >= 55:
        highlights.append("차별화 유지 시 경쟁 우위 가능성")
    else:
        highlights.append("경쟁 강도 부담이 있으나 차별화 여부에 따라 결과 변동 가능")

    if decision == "invest":
        decision_summary = (
            f"{company['company_name']}의 종합 점수 {total}점으로 투자 추천. "
            f"기술·시장 양면에서 긍정적 평가."
        )
    else:
        decision_summary = (
            f"{company['company_name']}의 종합 점수 {total}점으로 보류 판단. "
            f"추가 검증 후 재평가 권고."
        )

    decision_reason_detailed = " ".join(highlights) + (
        f" 종합 점수 {total}점({grade}등급)으로 "
        + ("투자 검토 기준 이상임." if decision == "invest" else "추가 검증 후 재평가가 적절함.")
    )

    # ── 5) 리스크/메트릭/누락 ──
    risk_factors = _build_risk_factors(company)
    headline_metrics = _build_headline_metrics(company)
    missing = _check_missing_inputs(company)

    # 신뢰도 결정
    score_fields = [company.get("tech_score", 0), company.get("market_score", 0), company.get("competitor_score", 0)]
    non_zero = sum(1 for s in score_fields if s > 0)
    if non_zero >= 3 and not missing:
        confidence = "high"
    elif non_zero >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    needs_review = len(missing) >= 2 or confidence == "low"
    status = "SUCCESS" if not missing else "NEED_MORE_EVIDENCE"

    # ── 6) State 기록 ──
    company["scorecard"] = items
    company["total_score"] = total
    company["investment_decision"] = decision
    company["grade"] = grade
    company["badge_label"] = badge_label
    company["badge_subtitle"] = badge_subtitle
    company["decision_summary"] = decision_summary
    company["investment_highlights"] = highlights
    company["decision_reason_detailed"] = decision_reason_detailed
    company["headline_metrics"] = headline_metrics
    company["risk_factors"] = risk_factors
    company["decision_confidence"] = confidence
    company["decision_status"] = status
    company["missing_inputs"] = missing
    company["needs_human_review"] = needs_review

    # 레거시 호환
    company["decision"] = decision
    company["decision_reason"] = decision_reason_detailed

    add_log(state, "decision", f"{company['company_name']} total={total}, grade={grade}, decision={decision}")
    return state
