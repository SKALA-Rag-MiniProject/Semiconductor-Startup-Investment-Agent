"""투자 판단 에이전트 (Scorecard Valuation Method — 반도체 스타트업 보정).

각 항목마다 어떤 웹 자료에서 어떤 정보를 발견하여 어떤 결론을 내렸는지
evidence를 상세 기록한다. PDF 참조는 REFERENCE 섹션으로 분리.
"""

from __future__ import annotations

import re
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


def _strip_urls(text: str) -> str:
    """본문 노출용 문자열에서 URL/마크다운 링크를 제거한다."""
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)  # [text](url) -> text
    text = re.sub(r"\(?\b(?:https?://|www\.)\S+\)?", "", text)  # bare url
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def _sanitize_evidence_lines(lines: list[str]) -> list[str]:
    return [_strip_urls(str(line)) for line in lines if _strip_urls(str(line))]


def _format_llm_evidence(evidence_list: list | dict, limit: int = 4) -> list[str]:
    """LLM evidence를 본문용 문자열로 변환한다 (URL은 본문에 노출하지 않음)."""
    if isinstance(evidence_list, dict):
        evidence_list = [evidence_list]
    if not isinstance(evidence_list, list):
        return []
    result = []
    for ev in evidence_list[:limit]:
        if not isinstance(ev, dict):
            continue
        src = ev.get("source_name", "")
        year = ev.get("source_year", "")
        claim = ev.get("claim", "")
        why = ev.get("why_it_matters", "")
        line = ""
        if src:
            line += f"[{src}"
            if year:
                line += f", {year}"
            line += "]"
        if claim:
            line += f" {claim}"
        if why:
            line += f" → {why}"

        if line.strip():
            result.append(line.strip())
    return _sanitize_evidence_lines(result)


def _format_web_sources(web_sources: list[dict], limit: int = 3) -> list[str]:
    """웹 검색 결과를 evidence 문자열로 변환한다 (URL은 본문에 노출하지 않음)."""
    result = []
    for src in web_sources[:limit]:
        title = src.get("title", "")
        snippet = src.get("snippet", "")[:100]
        if title:
            result.append(f"[웹] {title} — {snippet}...")
    return _sanitize_evidence_lines(result)


# ────────────────────────────────────────────────────────
# 스코어 산출 함수 (score, reason, evidence)
# ────────────────────────────────────────────────────────

def _score_founder_team(company: CompanyEvaluation) -> tuple[int, str, list[str]]:
    """창업자/팀 점수."""
    rubric = company.get("tech_rubric", {})
    rubric_scores = [row.get("score", 0) for row in rubric.values()] if rubric else []
    avg_rubric = sum(rubric_scores) / len(rubric_scores) if rubric_scores else 2.5

    doc_count = len(company.get("retrieved_docs", []))
    proof_ok = company.get("proof_status") == "verified"

    base = avg_rubric * 16
    if proof_ok:
        base += 8
    if doc_count >= EXECUTION_DOC_THRESHOLD:
        base += 5

    score = _clamp(base)

    # 근거: 웹 검색에서 팀 관련 정보, + 기술 루브릭 결과
    evidence = []

    # 본문에는 웹 근거 줄을 직접 노출하지 않고, REFERENCE 섹션에서만 URL/소스를 제시한다.
    evidence.append("웹 기반 근거는 REFERENCE 섹션 참조")

    if rubric:
        rubric_detail = ", ".join(f"{k}: {v.get('score', '-')}/5" for k, v in rubric.items())
        evidence.append(f"기술 문서 분석 결과 루브릭 평균 {avg_rubric:.1f}/5 ({rubric_detail}) → 팀 기술력 추정")
    evidence.append(f"논문/기술문서 {doc_count}건 검색, 근거 검증: {company.get('proof_status', 'unknown')}")

    if not evidence:
        evidence.append("팀 관련 직접 자료 부족 → 기술 루브릭 기반 간접 추정")

    if score >= 75:
        reason = "기술 루브릭 및 문서 기반 실행력·전문성이 높게 평가됨"
    elif score >= 60:
        reason = "팀 전문성은 확인되나 추가 검증이 필요함"
    else:
        reason = "팀 정보가 제한적이어서 보수적으로 평가함"
    return score, reason, _sanitize_evidence_lines(evidence)


def _score_market(company: CompanyEvaluation) -> tuple[int, str, list[str]]:
    """시장성: LLM evidence + 웹 검색 결과."""
    raw = company.get("market_score", 0.0)
    score = _clamp(raw * 100)

    evidence = []

    # LLM이 반환한 웹 기반 evidence (출처 + URL + 판단 포함)
    market_ev = company.get("market_evidence", [])
    evidence.extend(_format_llm_evidence(market_ev, limit=4))

    # 본문에는 웹 결과 raw 목록을 노출하지 않는다.
    if len(evidence) < 1:
        evidence.append("웹 기반 시장 근거는 REFERENCE 섹션 참조")

    # score_reason이 있으면 추가
    detail = company.get("market_detail", {})
    score_reason = detail.get("score_reason", "")
    if score_reason:
        evidence.append(f"LLM 점수 판단: {score_reason}")

    if not evidence:
        summary = company.get("market_summary", "")
        if summary:
            evidence.append(f"시장성 분석 결과: {summary[:150]}")

    if score >= 80:
        reason = "시장 규모 및 성장 가능성이 높음"
    elif score >= 60:
        reason = "시장 기회는 존재하나 채택 속도의 보수적 해석 필요"
    else:
        reason = "시장성 근거가 부족하여 보수적 평가"
    return score, reason, _sanitize_evidence_lines(evidence)


def _score_product_tech(company: CompanyEvaluation) -> tuple[int, str, list[str]]:
    """제품/기술력."""
    raw = company.get("tech_score", 0.0)
    score = _clamp(raw * 100)

    evidence = []

    # 기술 요약에서 핵심 문장 추출
    summary = company.get("tech_summary", "")
    if summary:
        sentences = [s.strip() for s in summary.replace(". ", ".\n").split("\n") if s.strip()]
        for s in sentences[:2]:
            evidence.append(f"기술 분석 결과: {s}")

    # 루브릭 세부
    rubric = company.get("tech_rubric", {})
    if rubric:
        rubric_detail = ", ".join(f"{k}: {v.get('score', '-')}/5" for k, v in rubric.items())
        evidence.append(f"루브릭 채점: {rubric_detail}")

    if score >= 80:
        reason = "기술 독창성과 구현 가능성이 높음"
    elif score >= 60:
        reason = "기술적 차별성은 있으나 구현 성숙도 보강 필요"
    else:
        reason = "기술력 근거가 제한적"
    return score, reason, _sanitize_evidence_lines(evidence)


def _score_competitive_advantage(company: CompanyEvaluation) -> tuple[int, str, list[str]]:
    """경쟁 우위: LLM evidence + 웹 검색 결과."""
    raw = company.get("competitor_score", 0.0)
    score = _clamp(raw * 100)

    evidence = []

    # LLM이 반환한 웹 기반 evidence
    comp_ev = company.get("competitor_evidence", [])
    evidence.extend(_format_llm_evidence(comp_ev, limit=4))

    # 본문에는 웹 결과 raw 목록을 노출하지 않는다.
    if len(evidence) < 1:
        evidence.append("웹 기반 경쟁 근거는 REFERENCE 섹션 참조")

    # score_reason
    detail = company.get("competitor_detail", {})
    score_reason = detail.get("score_reason", "")
    if score_reason:
        evidence.append(f"LLM 점수 판단: {score_reason}")

    if not evidence:
        summary = company.get("competitor_summary", "")
        if summary:
            evidence.append(f"경쟁사 분석 결과: {summary[:150]}")

    if score >= 70:
        reason = "진입장벽 또는 기술 차별화가 경쟁 우위로 작용"
    elif score >= 50:
        reason = "차별화 포인트는 있으나 객관적 비교 지표 부족"
    else:
        reason = "경쟁 우위 근거가 부족"
    return score, reason, _sanitize_evidence_lines(evidence)


def _score_track_record(company: CompanyEvaluation) -> tuple[int, str, list[str]]:
    """실적."""
    doc_count = len(company.get("retrieved_docs", []))
    proof_ok = company.get("proof_status") == "verified"
    tech_rubric = company.get("tech_rubric", {})
    maturity = tech_rubric.get("구현 성숙도", {}).get("score", 2)

    base = maturity * 14
    if proof_ok:
        base += 10
    if doc_count >= 3:
        base += 5

    score = _clamp(base)

    evidence = []

    evidence.append("웹 기반 실적 근거는 REFERENCE 섹션 참조")

    evidence.append(f"구현 성숙도 루브릭: {maturity}/5, 문서 검증: {company.get('proof_status', 'unknown')}")

    for note in company.get("proof_notes", [])[:2]:
        evidence.append(f"검증 로그: {note}")

    if score >= 70:
        reason = "PoC, 고객 검증 등 구체적 실적이 확인됨"
    elif score >= 50:
        reason = "일부 실적 근거가 있으나 상용 전환 확인 필요"
    else:
        reason = "실적 정보가 제한적이어서 보수적 평가"
    return score, reason, _sanitize_evidence_lines(evidence)


def _score_investment_terms(company: CompanyEvaluation) -> tuple[int, str, list[str]]:
    """투자조건."""
    score = 55
    reason = "투자조건 관련 상세 정보가 부족하여 보수적으로 평가"

    evidence = ["웹 기반 투자조건 근거는 REFERENCE 섹션 참조"]
    evidence.append("기업가치, 지분율, 투자 라운드 상세 정보 미입력 → 기본값 55점 적용")

    return score, reason, _sanitize_evidence_lines(evidence)


def _build_risk_factors(company: CompanyEvaluation) -> list[dict]:
    factors: list[dict] = []

    if company.get("market_score", 0.0) < 0.70:
        factors.append({
            "level": "HIGH", "title": "시장 채택 속도 불확실성",
            "detail": "시장 점수가 보수적으로 평가되어 상용 채택 속도가 예상보다 느릴 수 있음",
            "mitigation": "PoC 확대 및 전략적 고객 확보로 채택 가속 필요",
        })
    if company.get("tech_score", 0.0) < 0.80:
        factors.append({
            "level": "MED", "title": "기술 차별성 지속 가능성",
            "detail": "기술 우위가 경쟁사 추격 시 유지 가능한지 추가 검증 필요",
            "mitigation": "지속적 R&D 투자 및 특허 포트폴리오 강화",
        })
    if company.get("competitor_score", 0.0) < 0.60:
        factors.append({
            "level": "HIGH", "title": "글로벌 경쟁 심화",
            "detail": "대형 경쟁사의 시장 진입으로 경쟁 강도가 높아질 수 있음",
            "mitigation": "니치 시장 집중 또는 전략 파트너십 확보",
        })
    factors.append({
        "level": "MED", "title": "자본 집약적 구조",
        "detail": "반도체 스타트업 특성상 tape-out 및 양산 시 추가 자금 소요 가능",
        "mitigation": "전략 투자자 확보 및 후속 라운드 계획 확인 필요",
    })
    factors.append({
        "level": "LOW", "title": "투자조건 정보 제한",
        "detail": "기업가치, 지분율 등 상세 투자 조건 정보가 부족",
        "mitigation": "실사 단계에서 상세 조건 확인 필요",
    })
    order = {"HIGH": 0, "MED": 1, "LOW": 2}
    factors.sort(key=lambda f: order.get(f["level"], 9))
    return factors


def _check_missing_inputs(company: CompanyEvaluation) -> list[str]:
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
    company = get_current_company(state)

    items = []

    founder_score, founder_reason, founder_ev = _score_founder_team(company)
    items.append(make_scorecard_item("창업자/팀", founder_score, founder_reason, founder_ev))

    market_score, market_reason, market_ev = _score_market(company)
    items.append(make_scorecard_item("시장성", market_score, market_reason, market_ev))

    tech_score, tech_reason, tech_ev = _score_product_tech(company)
    items.append(make_scorecard_item("제품/기술력", tech_score, tech_reason, tech_ev))

    comp_score, comp_reason, comp_ev = _score_competitive_advantage(company)
    items.append(make_scorecard_item("경쟁 우위", comp_score, comp_reason, comp_ev))

    track_score, track_reason, track_ev = _score_track_record(company)
    items.append(make_scorecard_item("실적", track_score, track_reason, track_ev))

    terms_score, terms_reason, terms_ev = _score_investment_terms(company)
    items.append(make_scorecard_item("투자조건", terms_score, terms_reason, terms_ev))

    total = weighted_total(items)
    grade = score_to_grade(total)

    if total >= INVEST_THRESHOLD:
        decision, badge_label, badge_subtitle = "invest", "INVEST", "투자 추천"
    else:
        decision, badge_label, badge_subtitle = "hold", "HOLD", "보류"

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
        decision_summary = f"{company['company_name']}의 종합 점수 {total}점으로 투자 추천. 기술·시장 양면에서 긍정적 평가."
    else:
        decision_summary = f"{company['company_name']}의 종합 점수 {total}점으로 보류 판단. 추가 검증 후 재평가 권고."

    decision_reason_detailed = " ".join(highlights) + (
        f" 종합 점수 {total}점({grade}등급)으로 "
        + ("투자 검토 기준 이상임." if decision == "invest" else "추가 검증 후 재평가가 적절함.")
    )

    risk_factors = _build_risk_factors(company)
    missing = _check_missing_inputs(company)

    score_fields = [company.get("tech_score", 0), company.get("market_score", 0), company.get("competitor_score", 0)]
    non_zero = sum(1 for s in score_fields if s > 0)
    confidence = "high" if non_zero >= 3 and not missing else ("medium" if non_zero >= 2 else "low")
    needs_review = len(missing) >= 2 or confidence == "low"
    status = "SUCCESS" if not missing else "NEED_MORE_EVIDENCE"

    company.update({
        "scorecard": items, "total_score": total, "investment_decision": decision,
        "grade": grade, "badge_label": badge_label, "badge_subtitle": badge_subtitle,
        "decision_summary": decision_summary, "investment_highlights": highlights,
        "decision_reason_detailed": decision_reason_detailed,
        "headline_metrics": [], "risk_factors": risk_factors,
        "decision_confidence": confidence, "decision_status": status,
        "missing_inputs": missing, "needs_human_review": needs_review,
        "decision": decision, "decision_reason": decision_reason_detailed,
    })

    add_log(state, "decision", f"{company['company_name']} total={total}, grade={grade}, decision={decision}")
    return state
