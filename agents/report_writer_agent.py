"""보고서 생성 에이전트.

투자 판단 에이전트의 출력을 받아 정형화된 투자 평가 보고서를 마크다운으로 생성한다.
문서 구성: 헤더 → SUMMARY → 스코어카드 → 기업 개요 → 시장성 분석 → 기술력 요약
          → 리스크 요인 → 최종 투자의견 → REFERENCE
"""

from __future__ import annotations

from datetime import date
import re
from typing import List

from state import AgentState, CompanyEvaluation, add_log


# ────────────────────────────────────────────────────────
# 보고서 렌더링 헬퍼
# ────────────────────────────────────────────────────────

def _render_header(company: CompanyEvaluation, report_date: str) -> str:
    badge = f"[{company['badge_label']}] {company['badge_subtitle']} | 등급 {company['grade']}"
    return f"""---
CONFIDENTIAL | AI 스타트업 투자 에이전트 | 엔지니어 모드
---

# {company['company_name']}
투자 평가 보고서 | {report_date} | 작성 AI 투자 에이전트
{badge}"""


def _render_summary(company: CompanyEvaluation) -> str:
    decision_label = f"{company['badge_label']} {company['badge_subtitle']}"
    metrics_line = ""
    if company.get("headline_metrics"):
        parts = [f"{m['label']} {m['value']}" for m in company["headline_metrics"]]
        metrics_line = f"\n- 투자 현황: {' / '.join(parts)}"

    extra = ""
    if company.get("decision_status") == "NEED_MORE_EVIDENCE":
        extra = "\n- ⚠️ 추가 검증 권고"

    return f"""---

## ■ SUMMARY
- 투자 대상: {company['company_name']}
- 종합 점수: {company['total_score']} / 100점 ⇨ {decision_label} | 등급 {company['grade']}
- 핵심 근거: {company['decision_summary']}{metrics_line}{extra}"""


def _render_scorecard(company: CompanyEvaluation) -> str:
    def _strip_urls(text: str) -> str:
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1", text)
        text = re.sub(r"https?://\S+", "", text)
        return text.strip()

    lines = [
        "",
        "---",
        "",
        "## 1. 투자 판단 스코어카드 (Scorecard Valuation Method)",
        "| 평가 항목 | 비율 | 점수 (0-100) | 가중 점수 | 판단 |",
        "|-----------|------|-------------|-----------|------|",
    ]
    for item in company.get("scorecard", []):
        pct = f"{int(item['weight'] * 100)}%"
        lines.append(
            f"| {item['category']} | {pct} | {item['raw_score']} | {item['weighted_score']} | {item['judgement_label']} |"
        )
    # 종합 점수: 가중 점수 칸 아래에 표시
    lines.append(
        f"| **종합 점수 (Total Score)** | **100%** | | **{company['total_score']} / 100** | **{company['grade']}등급** |"
    )

    # ── 항목별 판단 근거 & 참고 자료 ──
    lines.append("")
    lines.append("### 항목별 판단 근거 및 참고 자료")
    for item in company.get("scorecard", []):
        lines.append(f"**{item['category']}** ({item['raw_score']}점 / {item['judgement_label']})")
        lines.append(f"- 판단: {item['reason']}")
        evidence = item.get("evidence", [])
        if evidence:
            for ev in evidence:
                ev_text = _strip_urls(str(ev))
                if not ev_text:
                    continue
                if ev_text.startswith("[웹]"):
                    continue
                if "http://" in ev_text or "https://" in ev_text or "www." in ev_text:
                    continue
                lines.append(f"- {ev_text}")
        else:
            lines.append("- (입력 데이터 부족)")
        lines.append("")

    return "\n".join(lines)


def _render_company_overview(company: CompanyEvaluation) -> str:
    """기업 개요 섹션."""
    rows = [
        ("기업명", company["company_name"]),
    ]
    table = "\n".join(f"| {k} | {v} |" for k, v in rows)
    return f"""
## 2. 기업 개요 (Company Overview)
| 항목 | 내용 |
|------|------|
{table}"""


def _render_market_analysis(company: CompanyEvaluation) -> str:
    parts = ["", "## 3. 시장성 분석 (Market Analysis)", ""]

    # headline metrics 카드
    metrics = company.get("headline_metrics", [])
    if metrics:
        header = " | ".join(m["label"] for m in metrics)
        values = " | ".join(m["value"] for m in metrics)
        sep = " | ".join("---" for _ in metrics)
        parts.append(f"| {header} |")
        parts.append(f"|{sep}|")
        parts.append(f"| {values} |")
        parts.append("")

    # 시장성 요약
    summary = company.get("market_summary", "")
    if summary:
        parts.append("### 주요 분석")
        sentences = [s.strip() for s in summary.replace(". ", ".\n").split("\n") if s.strip()]
        for s in sentences[:6]:
            parts.append(f"- {s}")
    else:
        parts.append("### 주요 분석")
        parts.append("- 시장성 요약 생성 실패 또는 데이터 부족")

    # 시장성 점수/상태를 항상 표시
    market_score = company.get("market_score")
    if market_score is not None:
        parts.append(f"- 시장성 점수(정규화): {market_score:.2f}")
    market_detail = company.get("market_detail", {})
    confidence = market_detail.get("confidence")
    if confidence:
        parts.append(f"- 분석 신뢰도: {confidence}")
    score_reason = market_detail.get("score_reason")
    if score_reason:
        parts.append(f"- 점수 근거: {score_reason}")

    # 경쟁 포지셔닝
    comp_summary = company.get("competitor_summary", "")
    if comp_summary and len(comp_summary) >= 50:
        parts.append("")
        parts.append("### 경쟁 포지셔닝")
        sentences = [s.strip() for s in comp_summary.replace(". ", ".\n").split("\n") if s.strip()]
        for s in sentences[:4]:
            parts.append(f"- {s}")

    return "\n".join(parts)


def _render_tech_summary(company: CompanyEvaluation) -> str:
    parts = ["", "## 4. 기술력 요약 (Technology Summary)", ""]

    summary = company.get("tech_summary", "")
    if summary:
        parts.append("### 핵심 기술 차별화 포인트")
        sentences = [s.strip() for s in summary.replace(". ", ".\n").split("\n") if s.strip()]
        for s in sentences[:6]:
            parts.append(f"- {s}")

    rubric = company.get("tech_rubric", {})
    if rubric:
        parts.append("")
        parts.append("### 기술 세부 평가")
        for name, row in rubric.items():
            parts.append(f"- {name}: {row.get('score', '-')}/5")

    return "\n".join(parts)


def _render_risk_factors(company: CompanyEvaluation) -> str:
    parts = ["", "## 5. 리스크 요인 (Risk Factors)", ""]
    factors = company.get("risk_factors", [])
    if not factors:
        parts.append("- 현재 근거 기준 중대한 리스크는 제한적임")
        return "\n".join(parts)

    for f in factors:
        parts.append(f"**{f['level']}** | {f['title']}")
        parts.append(f"- {f['detail']}")
        parts.append(f"- **대응 전략**: {f['mitigation']}")
        parts.append("")

    return "\n".join(parts)


def _render_final_opinion(company: CompanyEvaluation) -> str:
    parts = [
        "---",
        "",
        "## ■ 최종 투자의견",
        f"**■ 최종 투자 의견: {company['badge_label']} | {company['badge_subtitle']} "
        f"(등급 {company['grade']} / 종합 점수 {company['total_score']} / 100)**",
    ]
    for h in company.get("investment_highlights", []):
        parts.append(f"- {h}")

    if company.get("decision_status") == "NEED_MORE_EVIDENCE":
        parts.append("")
        parts.append("⚠️ 일부 입력 데이터가 불충분하여 추가 검증을 권고합니다.")

    if company.get("needs_human_review"):
        parts.append("")
        parts.append("※ 일부 입력 데이터 부족으로 전문가 검토를 권고합니다.")

    parts.append("")
    parts.append("본 보고서는 AI 기반 분석에 의해 생성되었습니다. 최종 투자 판단은 담당 에이전트가 수행합니다.")
    return "\n".join(parts)


def _render_reference(company: CompanyEvaluation) -> str:
    parts = ["", "---", "", "## REFERENCE", ""]

    # PDF 문서
    docs = company.get("retrieved_docs", [])
    if docs:
        parts.append("### 참고 논문/기술 문서")
        seen = set()
        for doc in docs:
            source = doc.get("source", "")
            title = doc.get("title", source)
            key = source or title
            if key in seen:
                continue
            seen.add(key)
            parts.append(f"- {title} ({source})")

    # 웹 검색 evidence (시장성)
    market_ev = company.get("market_evidence", [])
    if market_ev:
        parts.append("")
        parts.append("### 시장성 분석 참고 자료")
        for ev in market_ev:
            src = ev.get("source_name", "")
            year = ev.get("source_year", "")
            url = ev.get("url", "")
            claim = ev.get("claim", "")
            ref = f"[{src}, {year}]" if year else f"[{src}]"
            line = f"- {ref} {claim}"
            if url:
                line += f" ({url})"
            parts.append(line)

    # 웹 검색 evidence (경쟁사)
    comp_ev = company.get("competitor_evidence", [])
    if comp_ev:
        parts.append("")
        parts.append("### 경쟁사 분석 참고 자료")
        for ev in comp_ev:
            src = ev.get("source_name", "")
            year = ev.get("source_year", "")
            url = ev.get("url", "")
            claim = ev.get("claim", "")
            ref = f"[{src}, {year}]" if year else f"[{src}]"
            line = f"- {ref} {claim}"
            if url:
                line += f" ({url})"
            parts.append(line)

    # 웹 검색 원본 소스 (시장성)
    market_web = company.get("market_web_sources", [])
    if market_web:
        parts.append("")
        parts.append("### 시장성 웹 검색 소스")
        for ws in market_web[:8]:
            title = ws.get("title", "")
            url = ws.get("url", "")
            if title and url:
                parts.append(f"- [{title}]({url})")

    # 웹 검색 원본 소스 (경쟁사)
    comp_web = company.get("competitor_web_sources", [])
    if comp_web:
        parts.append("")
        parts.append("### 경쟁사 웹 검색 소스")
        for ws in comp_web[:8]:
            title = ws.get("title", "")
            url = ws.get("url", "")
            if title and url:
                parts.append(f"- [{title}]({url})")

    if not docs and not market_ev and not comp_ev and not market_web and not comp_web:
        parts.append("- 참고 문서 없음")

    return "\n".join(parts)


# ────────────────────────────────────────────────────────
# 기업별 보고서 생성
# ────────────────────────────────────────────────────────

def _generate_single_report(company: CompanyEvaluation, report_date: str) -> str:
    """한 기업에 대한 전체 투자 평가 보고서를 생성한다."""
    sections = [
        _render_header(company, report_date),
        _render_summary(company),
        _render_scorecard(company),
        _render_company_overview(company),
        _render_market_analysis(company),
        _render_tech_summary(company),
        _render_risk_factors(company),
        _render_final_opinion(company),
        _render_reference(company),
    ]
    return "\n".join(sections)


# ────────────────────────────────────────────────────────
# 비교 보고서 헬퍼 (다수 기업 비교용)
# ────────────────────────────────────────────────────────

def _render_comparison_header(state: AgentState, report_date: str) -> str:
    return f"""---
CONFIDENTIAL | AI 스타트업 투자 에이전트 | 엔지니어 모드
---

# AI 반도체 스타트업 투자 비교 보고서
투자 평가 보고서 | {report_date} | 작성 AI 투자 에이전트

## 평가 질문
- {state['question']}"""


def _render_comparison_ranking(ranked: List[CompanyEvaluation]) -> str:
    best = ranked[0]
    lines = [
        "",
        "---",
        "",
        "## ■ SUMMARY",
        f"- 최우선 투자 검토 대상: {best['company_name']}",
        f"- 최종 판단: {best['badge_label']} {best['badge_subtitle']}",
        f"- 핵심 근거: {best['decision_summary']}",
        "",
        "## 전체 순위",
        "| 순위 | 기업명 | 종합 점수 | 등급 | 판단 |",
        "|------|--------|-----------|------|------|",
    ]
    for idx, c in enumerate(ranked, 1):
        lines.append(
            f"| {idx} | {c['company_name']} | {c['total_score']} / 100 | {c['grade']} | {c['badge_label']} |"
        )
    return "\n".join(lines)


# ────────────────────────────────────────────────────────
# 메인 에이전트
# ────────────────────────────────────────────────────────

def report_writer_agent(state: AgentState) -> AgentState:
    """State 결과를 읽어 최종 투자 평가 보고서를 생성한다."""
    report_date = date.today().strftime("%Y. %m. %d")
    ranked = sorted(
        state["companies"].values(),
        key=lambda c: c.get("total_score", 0.0),
        reverse=True,
    )

    if len(ranked) == 1:
        report = _generate_single_report(ranked[0], report_date)
    else:
        parts = [_render_comparison_header(state, report_date)]
        parts.append(_render_comparison_ranking(ranked))
        for company in ranked:
            parts.append("")
            parts.append("---")
            parts.append(f"\n# {company['company_name']} 상세 분석")
            parts.append(_render_summary(company))
            parts.append(_render_scorecard(company))
            parts.append(_render_company_overview(company))
            parts.append(_render_market_analysis(company))
            parts.append(_render_tech_summary(company))
            parts.append(_render_risk_factors(company))
            parts.append(_render_final_opinion(company))
            parts.append(_render_reference(company))
        report = "\n".join(parts)

    state["final_report"] = report
    state["answer"] = report
    add_log(state, "report", "final report generated")
    return state
