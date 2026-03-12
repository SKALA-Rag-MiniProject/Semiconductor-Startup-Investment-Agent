"""시장성 에이전트 — 웹 검색 + LLM 기반 시장 분석.

프롬프트 03번 기반: TAM/SAM/SOM, CAGR, 수요 촉진 요인, 고객 도입 가능성,
지역별 기회를 웹 검색으로 조사하고 LLM이 구조화 JSON으로 평가한다.
"""

from __future__ import annotations

from state import AgentState, add_log, get_current_company
from llm_client import call_llm_json, web_search


# ────────────────────────────────────────────────────────
# 프롬프트
# ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
당신은 반도체 스타트업 투자 평가를 위한 시장성 분석 에이전트다.

목표:
- 특정 스타트업이 속한 반도체 세부 시장의 시장성을 투자 관점에서 평가한다.
- 시장 규모, 성장성, 수요 촉진 요인, 고객 도입 가능성, 지역별 기회와 제약을 분석한다.
- 반드시 제공된 웹 검색 결과를 바탕으로만 판단한다.

행동 원칙:
1. 기업 자체 홍보 문구를 그대로 신뢰하지 말고, 산업 리포트/시장 조사 기관/공식 자료/신뢰 가능한 뉴스 중심으로 교차 검증한다.
2. 시장 규모는 가능하면 TAM, SAM, SOM으로 구분한다.
3. 성장성은 CAGR, 수요 증가 배경, 정책/산업 변화, 고객군 확대 가능성으로 판단한다.
4. 숫자나 전망이 상충하면 더 보수적인 해석을 우선한다.
5. 정보가 부족한 항목은 추정하지 말고 "근거 부족" 또는 "추가 검증 필요"로 표시한다.
6. 시장을 training과 inference로 구분하여 분석한다.
7. 최종적으로 투자 평가용 market_score(0~25)를 산출한다.

자기 점검 규칙:
- TAM/SAM/SOM 중 2개 이상이 비어 있으면 NEED_MORE_EVIDENCE로 판단한다.
- CAGR 출처가 2개 미만이면 "근거 부족"으로 표시한다.
- evidence가 3개 미만이면 최종 점수를 낮은 신뢰도로 표시한다.

출력 규칙:
- 반드시 지정된 JSON 형식으로만 출력한다.
- 근거 없는 단정 표현을 금지한다.
- 각 핵심 판단에는 evidence 배열을 포함하며, 출처에 발행 연도를 반드시 기재한다.
"""


def _build_user_prompt(
    company_name: str,
    question: str,
    tech_summary: str,
    search_results: list,
    retrieved_docs: list,
) -> str:
    search_text = "\n".join(
        f"- [{r['title']}]({r['url']}): {r['snippet']}"
        for r in search_results
    )

    # PDF 임베딩 검색으로 가져온 원본 청크
    doc_texts = []
    for i, doc in enumerate(retrieved_docs[:5], 1):
        source = doc.get("source", "unknown")
        text = doc.get("text", "")[:800]
        doc_texts.append(f"[문서{i} / {source}]\n{text}")
    doc_section = "\n\n".join(doc_texts) if doc_texts else "(PDF 검색 결과 없음)"

    return f"""\
다음 스타트업의 시장성을 분석해줘.

[기업 정보]
- 회사명: {company_name}
- 핵심 기술/카테고리: AI accelerator / NPU
- 세부 반도체 영역: NPU, AI inference accelerator

[기술 요약 (선행 에이전트 결과)]
{tech_summary}

[PDF 논문/기술 문서에서 검색된 원본 내용]
{doc_section}

[사용자 질문]
{question}

[웹 검색 결과]
{search_text}

[분석 목적]
이 분석은 반도체 스타트업 투자 평가용이다.
시장성 평가는 총 25점 만점 기준으로 수행한다.

[반드시 분석할 항목]
1. 이 기업이 속한 시장의 정의 (training vs inference 구분 포함)
2. TAM / SAM / SOM (데이터 부족 시 "산정 불가" 명시)
3. 시장 규모와 성장률 (최소 2개 이상 시장 리포트 출처의 CAGR 비교)
4. 수요 촉진 요인 (AI/GenAI 확산, 데이터센터 투자, 자율주행, 정부 정책 등)
5. 주요 고객군과 실제 도입 가능성
6. 지역별 기회와 제약
7. 시장 진입의 현실적 제약
8. 이 시장이 반도체 스타트업 투자 대상으로서 매력적인 이유와 한계
9. market_score(0~25)와 점수 근거

[출력 형식]
아래 JSON 형식으로만 답변해.
{{
  "market_summary": "2~3문장 핵심 요약",
  "market_definition": "시장 정의 및 training/inference 구분",
  "tam_sam_som": {{
    "tam": "금액 및 연도",
    "tam_source": "출처명",
    "sam": "금액 또는 산정 불가",
    "sam_reasoning": "SAM 산출 근거",
    "som": "금액 또는 산정 불가",
    "som_reasoning": "SOM 산출 근거 또는 부족 사유"
  }},
  "market_growth": {{
    "current_size": "금액 및 기준 연도",
    "forecast_size": "금액 및 목표 연도",
    "cagr_estimates": [
      {{"source": "", "cagr": "", "period": ""}}
    ],
    "consensus_cagr": "보수적 종합 판단"
  }},
  "demand_drivers": [
    {{
      "driver": "",
      "description": "",
      "impact_level": "high / medium / low",
      "evidence_summary": ""
    }}
  ],
  "customer_adoption": {{
    "target_customers": [
      {{"type": "", "examples": "", "adoption_likelihood": ""}}
    ],
    "barriers": []
  }},
  "regional_opportunities": [
    {{
      "region": "",
      "opportunity": "",
      "constraint": "",
      "policy_factor": ""
    }}
  ],
  "market_entry_barriers": [
    {{
      "barrier": "",
      "severity": "high / medium / low",
      "detail": ""
    }}
  ],
  "investment_attractiveness": {{
    "reasons": [],
    "limitations": []
  }},
  "market_score": 0,
  "score_reason": "",
  "confidence": "high / medium / low",
  "market_status": "SUCCESS / FAILED / NEED_MORE_EVIDENCE",
  "market_error": "",
  "evidence": [
    {{
      "claim": "",
      "source_name": "",
      "source_year": "",
      "url": "",
      "why_it_matters": ""
    }}
  ]
}}

[추가 규칙]
- 숫자가 없으면 억지로 채우지 마.
- 회사 홍보성 문구보다 제3자 자료를 우선해.
- CAGR은 최소 2개 출처를 비교해서 보수적 값을 채택해.
- evidence의 source_year는 반드시 기재해.
- 투자자 관점에서 읽히도록 간결하고 근거 중심으로 작성해.
"""


# ────────────────────────────────────────────────────────
# 에이전트 본체
# ────────────────────────────────────────────────────────

def market_eval_agent(state: AgentState) -> AgentState:
    """웹 검색 + LLM 기반 시장성 분석을 수행한다."""
    company = get_current_company(state)
    company_name = company["company_name"]
    tech_summary = company.get("tech_summary", "")

    # 1) 웹 검색 수행
    search_queries = [
        f"{company_name} AI accelerator market size forecast 2025 2030",
        f"AI inference chip market TAM SAM CAGR growth report",
        f"NPU AI accelerator semiconductor market opportunity",
        f"{company_name} semiconductor startup funding customers",
    ]
    add_log(state, "market_eval", f"웹 검색 시작: {company_name}")
    search_results = web_search(search_queries)
    add_log(state, "market_eval", f"검색 결과 {len(search_results)}건 수집")

    # 2) LLM 호출 (PDF 원본 청크도 함께 전달)
    user_prompt = _build_user_prompt(
        company_name=company_name,
        question=state["question"],
        tech_summary=tech_summary,
        search_results=search_results,
        retrieved_docs=company.get("retrieved_docs", []),
    )

    result = call_llm_json(SYSTEM_PROMPT, user_prompt)

    # 3) State에 기록
    if "error" in result:
        company["market_summary"] = f"LLM 응답 파싱 실패: {result.get('error', '')}"
        company["market_score"] = 0.50  # 보수적 기본값
        add_log(state, "market_eval", f"{company_name} LLM 파싱 실패, 기본값 사용")
    else:
        company["market_summary"] = result.get("market_summary", "")
        # market_score: 0~25 → 0.0~1.0 정규화
        raw_score = result.get("market_score", 12)
        company["market_score"] = round(min(max(raw_score / 25.0, 0.0), 1.0), 2)

        # evidence를 state에 저장 (보고서 REFERENCE용)
        evidence = result.get("evidence", [])
        if evidence:
            company.setdefault("market_evidence", evidence)

        add_log(
            state, "market_eval",
            f"{company_name} market_score={company['market_score']} "
            f"(raw={raw_score}/25, status={result.get('market_status', 'N/A')})"
        )

    return state
