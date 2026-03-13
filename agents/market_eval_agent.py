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
당신은 반도체 스타트업 투자용 시장성 분석 에이전트다.
제공된 웹/PDF 근거만 사용해 보수적으로 판단하고 JSON만 출력한다.

원칙:
1) 홍보성 문구보다 제3자 자료 우선.
2) training vs inference 구분.
3) TAM/SAM/SOM, 성장률(CAGR), 수요요인, 고객도입, 지역 기회/제약, 진입장벽을 간결히 평가.
4) 근거 부족 시 추정하지 말고 NEED_MORE_EVIDENCE.
5) market_score는 0~25 정수.
6) evidence에는 source_name/source_year/url 포함.
"""

RETRY_SYSTEM_PROMPT = """\
당신은 반도체 스타트업 시장성 평가기다.
반드시 JSON object만 출력한다.
설명 문장, 코드블록, 마크다운을 절대 출력하지 않는다.
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
        for r in search_results[:6]
    )

    # PDF 임베딩 검색으로 가져온 원본 청크
    doc_texts = []
    for i, doc in enumerate(retrieved_docs[:3], 1):
        source = doc.get("source", "unknown")
        text = doc.get("text", "")[:450]
        doc_texts.append(f"[문서{i} / {source}]\n{text}")
    doc_section = "\n\n".join(doc_texts) if doc_texts else "(PDF 검색 결과 없음)"

    return f"""\
기업: {company_name}
질문: {question}
기술 요약: {tech_summary[:500]}

[PDF 근거]
{doc_section}

[웹 근거]
{search_text}

아래 JSON만 출력:
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
  "market_status": "SUCCESS / NEED_MORE_EVIDENCE",
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

규칙:
- 숫자 근거 부족 시 "산정 불가" 또는 NEED_MORE_EVIDENCE.
- CAGR은 가능하면 2개 출처 비교 후 보수적으로 정리.
- evidence는 핵심 3~5개만.
"""


def _build_retry_user_prompt(
    company_name: str,
    question: str,
    search_results: list,
    retrieved_docs: list,
) -> str:
    web_lines = []
    for r in search_results[:8]:
        title = (r.get("title", "") or "").strip()
        snippet = (r.get("snippet", "") or "").strip()[:220]
        if title or snippet:
            web_lines.append(f"- {title}: {snippet}")
    web_text = "\n".join(web_lines) if web_lines else "- (검색 결과 없음)"

    doc_lines = []
    for d in retrieved_docs[:3]:
        source = d.get("source", "unknown")
        text = (d.get("text", "") or "").strip()[:280]
        if text:
            doc_lines.append(f"- {source}: {text}")
    doc_text = "\n".join(doc_lines) if doc_lines else "- (문서 근거 없음)"

    return f"""\
기업: {company_name}
질문: {question}

[웹 근거 요약]
{web_text}

[PDF 근거 요약]
{doc_text}

아래 JSON만 출력:
{{
  "market_summary": "2~3문장",
  "market_score": 0,
  "score_reason": "1~2문장",
  "confidence": "high|medium|low",
  "market_status": "SUCCESS|NEED_MORE_EVIDENCE",
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

규칙:
- market_score는 0~25 정수.
- 수치 근거가 부족하면 market_status를 NEED_MORE_EVIDENCE로 둔다.
- evidence는 최대 4개.
"""


def _fallback_market_result(company_name: str, search_results: list, retrieved_docs: list, error_msg: str) -> dict:
    """LLM JSON 파싱 실패 시에도 시장성 결과를 생성하기 위한 규칙 기반 fallback."""
    snippets = " ".join((r.get("snippet", "") or "") for r in search_results).lower()
    doc_blob = " ".join((d.get("text", "") or "") for d in retrieved_docs).lower()
    blob = f"{snippets} {doc_blob}"

    score = 0.58
    reasons = ["웹/문서 근거 기반 보수적 평가를 적용함."]

    if any(k in blob for k in ["growth", "cagr", "forecast", "market size", "tams", "tam"]):
        score += 0.05
        reasons.append("시장 성장 또는 규모 관련 신호가 일부 확인됨.")
    else:
        reasons.append("시장 규모/성장 수치 근거가 부족함.")

    if any(k in blob for k in ["customer", "deployment", "adoption", "design win", "contract"]):
        score += 0.04
        reasons.append("고객 도입/상용화 관련 단서가 일부 확인됨.")
    else:
        reasons.append("고객 도입 증거는 제한적임.")

    if any(k in blob for k in ["competition", "incumbent", "barrier", "qualification"]):
        score -= 0.03
        reasons.append("경쟁/도입 장벽 요인이 존재함.")

    score = round(min(max(score, 0.0), 1.0), 2)
    summary = f"{company_name} 시장성은 보수적으로 {score:.2f}로 평가됨. " + " ".join(reasons)

    return {
        "market_summary": summary,
        "market_score": score,
        "market_evidence": [],
        "market_detail": {
            "score_reason": "규칙 기반 대체 분석 사용",
            "confidence": "low",
            "market_status": "FALLBACK_USED",
            "market_error": error_msg[:200],
        },
    }


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

    # 2-1) 1차 JSON 파싱 실패 시, 축약 프롬프트로 1회 재시도
    if "error" in result:
        retry_prompt = _build_retry_user_prompt(
            company_name=company_name,
            question=state["question"],
            search_results=search_results,
            retrieved_docs=company.get("retrieved_docs", []),
        )
        retry_result = call_llm_json(
            RETRY_SYSTEM_PROMPT,
            retry_prompt,
            temperature=0.0,
            max_tokens=1800,
        )
        if "error" not in retry_result:
            result = retry_result
            add_log(state, "market_eval", f"{company_name} 시장성 JSON 파싱 재시도 성공")
        else:
            add_log(state, "market_eval", f"{company_name} 시장성 JSON 파싱 재시도 실패")

    # 3) 웹 검색 결과 자체를 state에 저장 (보고서 참고자료용)
    company["market_web_sources"] = [
        {"title": r["title"], "url": r["url"], "snippet": r["snippet"]}
        for r in search_results if r.get("url")
    ]

    # 4) LLM 결과를 State에 기록
    if "error" in result:
        fallback = _fallback_market_result(
            company_name=company_name,
            search_results=search_results,
            retrieved_docs=company.get("retrieved_docs", []),
            error_msg=result.get("error", ""),
        )
        company["market_summary"] = fallback["market_summary"]
        company["market_score"] = fallback["market_score"]
        company["market_evidence"] = fallback["market_evidence"]
        company["market_detail"] = fallback["market_detail"]
        add_log(
            state,
            "market_eval",
            f"{company_name} LLM 파싱 실패 -> fallback 적용 (market_score={company['market_score']})",
        )
    else:
        company["market_summary"] = result.get("market_summary", "")
        raw_score = result.get("market_score", 12)
        if isinstance(raw_score, dict):
            raw_score = raw_score.get("score", raw_score.get("value", 12))
        try:
            raw_score = float(raw_score)
        except (TypeError, ValueError):
            raw_score = 12.0
        company["market_score"] = round(min(max(raw_score / 25.0, 0.0), 1.0), 2)

        # LLM evidence 저장
        evidence = result.get("evidence", [])
        if isinstance(evidence, dict):
            evidence = [evidence]
        company["market_evidence"] = evidence if isinstance(evidence, list) else []

        # 전체 LLM 분석 결과도 저장 (상세 보고서용)
        company["market_detail"] = {
            k: result.get(k) for k in (
                "market_definition", "tam_sam_som", "market_growth",
                "demand_drivers", "score_reason", "confidence",
            ) if result.get(k)
        }

        # LLM 응답이 형식상 성공해도 핵심 값이 비어 있으면 fallback으로 보강
        if not company["market_summary"]:
            fallback = _fallback_market_result(
                company_name=company_name,
                search_results=search_results,
                retrieved_docs=company.get("retrieved_docs", []),
                error_msg="market_summary empty",
            )
            company["market_summary"] = fallback["market_summary"]
            company["market_score"] = fallback["market_score"]
            if not company.get("market_detail"):
                company["market_detail"] = fallback["market_detail"]
            add_log(state, "market_eval", f"{company_name} market_summary 비어있음 -> fallback 보강")

        add_log(
            state, "market_eval",
            f"{company_name} market_score={company['market_score']} "
            f"(raw={raw_score}/25, status={result.get('market_status', 'N/A')})"
        )

    return state
