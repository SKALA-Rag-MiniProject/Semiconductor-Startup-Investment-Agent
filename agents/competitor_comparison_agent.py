"""경쟁사 에이전트 — 웹 검색 + LLM 기반 경쟁 분석.

프롬프트 04번 기반: 직접/간접 경쟁사 식별, 성능·생태계·제조 비교,
해자 방어 가능성, M&A 동향을 웹 검색으로 조사하고 LLM이 구조화 JSON으로 평가한다.
"""

from __future__ import annotations

from state import AgentState, add_log, get_current_company
from llm_client import call_llm_json, web_search


# ────────────────────────────────────────────────────────
# 프롬프트
# ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
당신은 반도체 스타트업 투자 평가를 위한 경쟁사 분석 에이전트다.

목표:
- 특정 반도체 스타트업과 직접/간접 경쟁하는 기업을 식별한다.
- 제품, 기술, 성능 지표, 고객군, 파트너십, 양산 가능성, 진입장벽, IP/생태계 측면에서 경쟁 구도를 비교한다.
- 최종적으로 대상 기업의 경쟁 우위와 취약점을 정리하고 competition_score(0~10)을 산출한다.

행동 원칙:
1. 경쟁사는 같은 제품을 파는 회사뿐 아니라, 동일 고객 예산을 두고 경쟁하는 대체 기술/플랫폼도 포함한다. 특히 하이퍼스케일러의 자체 커스텀 실리콘(Google TPU, AWS Trainium, Microsoft Maia 등)은 반드시 간접 경쟁사로 검토한다.
2. 반도체 산업 특성을 반영해 다음을 모두 비교한다:
   - 성능 지표: TOPS/W(전력효율), TFLOPS, 레이턴시
   - 생태계: 소프트웨어 스택, 컴파일러, 프레임워크 호환성 (특히 CUDA 호환 여부)
   - 제조: 파운드리/패키징 파트너, 공정 노드
   - 상용화: 양산 여부, 고객 검증(PoC/design win), 펀딩 규모
3. 경쟁사의 최근 인수합병(M&A), 대규모 펀딩, 전략적 제휴를 반드시 확인한다.
4. 기사성 표현이나 과장된 마케팅 문구는 그대로 사용하지 않는다.
5. 비교 항목이 불명확하면 "직접 비교 불가"라고 명시한다.
6. 정보가 없는 항목은 추정하지 않는다.
7. 최종적으로 투자 평가용 competition_score(0~10)을 산출한다.

자기 점검 규칙:
- 직접 경쟁사와 간접 경쟁사 구분이 안 되면 NEED_MORE_EVIDENCE로 판단한다.
- 정량 지표가 부족하면 "정성 비교 중심"이라고 명시한다.
- evidence가 부족하면 competition_score에 low confidence를 부여한다.

출력 규칙:
- 반드시 지정된 JSON 형식으로만 출력한다.
- 핵심 비교는 표준화된 필드에 맞춰 작성한다.
- 모든 주요 판단에는 evidence를 포함하며, 출처에 발행 연도를 반드시 기재한다.
"""


def _build_user_prompt(
    company_name: str,
    question: str,
    tech_summary: str,
    market_summary: str,
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
다음 스타트업의 경쟁사와 경쟁 우위를 분석해줘.

[대상 기업 정보]
- 회사명: {company_name}
- 핵심 기술/카테고리: AI accelerator / NPU
- 세부 반도체 영역: NPU, AI inference accelerator

[기술 요약 (선행 에이전트)]
{tech_summary}

[시장성 요약 (선행 에이전트)]
{market_summary}

[PDF 논문/기술 문서에서 검색된 원본 내용]
{doc_section}

[사용자 질문]
{question}

[웹 검색 결과]
{search_text}

[분석 목적]
이 분석은 반도체 스타트업 투자 평가용이다.
경쟁 우위 평가는 총 10점 만점 기준으로 수행한다.

[반드시 분석할 항목]
1. 직접 경쟁사 3~5개 (동일 제품/시장 세그먼트) — 각 경쟁사의 최근 펀딩/M&A 현황 포함
2. 간접 경쟁사 또는 대체 기술 1~3개 — 하이퍼스케일러 커스텀 실리콘 반드시 검토
3. 정량적 성능 비교 (TOPS/W, TFLOPS, 레이턴시, TCO — 비교 불가 항목은 명시)
4. 생태계 비교 (CUDA 호환 여부, 자체 컴파일러, 프레임워크 지원)
5. 제조/공급망 비교 (파운드리, 공정 노드, 패키징)
6. 대상 기업의 해자(moat) 방어 가능성
7. 경쟁 열위 요인
8. 경쟁 구도 변화 시나리오 (bull/base/bear)
9. competition_score(0~10)와 점수 근거

[출력 형식]
아래 JSON 형식으로만 답변해.
{{
  "competition_summary": "2~3문장 핵심 요약",
  "market_context": {{
    "dominant_player": "",
    "dominant_market_share": "",
    "market_trend": "통합/분산/커스텀화 등"
  }},
  "direct_competitors": [
    {{
      "name": "",
      "country": "",
      "reason_for_competition": "",
      "funding_or_acquisition": "최근 펀딩/M&A 현황",
      "comparison_points": {{
        "product_positioning": "",
        "technology": "",
        "performance_metrics": {{
          "tops_per_watt": "수치 또는 비교 불가",
          "tflops": "수치 또는 비교 불가",
          "latency": "수치 또는 비교 불가",
          "tco_advantage": "수치 또는 비교 불가"
        }},
        "commercial_stage": "",
        "software_ecosystem": "",
        "manufacturing": "파운드리/공정/패키징",
        "ip_or_barrier": ""
      }}
    }}
  ],
  "indirect_competitors": [
    {{
      "name": "",
      "type": "하이퍼스케일러 커스텀 / 대체 아키텍처 / 소프트웨어 대체",
      "reason_for_competition": "",
      "threat_level": "high / medium / low",
      "comparison_points": {{
        "key_advantage": "",
        "key_limitation": "",
        "relevance_to_target": ""
      }}
    }}
  ],
  "target_company_advantages": [],
  "target_company_disadvantages": [],
  "defensibility": {{
    "moat_types": [
      {{
        "type": "기술적 IP / 소프트웨어 생태계 / 고객 락인 등",
        "strength": "strong / moderate / weak",
        "evidence": ""
      }}
    ],
    "overall_defensibility": "strong / moderate / weak",
    "note": ""
  }},
  "competition_scenario": {{
    "bull_case": "경쟁이 유리해지는 시나리오",
    "base_case": "현재 추세 유지 시나리오",
    "bear_case": "경쟁이 불리해지는 시나리오"
  }},
  "competition_risks": [],
  "competition_score": 0,
  "score_reason": "",
  "confidence": "high / medium / low",
  "competitor_status": "SUCCESS / FAILED / NEED_MORE_EVIDENCE",
  "competitor_error": "",
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
- 같은 산업 내 유명 기업을 무조건 넣지 말고 실제 경쟁 관계가 있는 경우만 넣어.
- 비교 가능한 항목만 비교해. 벤치마크가 미공개면 "비교 불가"로 명시해.
- 성능 비교 시 TOPS/W, TFLOPS 등 정량 지표를 우선 사용해.
- 소프트웨어 생태계가 하드웨어 성능보다 강력한 진입장벽이 될 수 있으므로 반드시 분석해.
- 경쟁사의 최근 M&A/펀딩 현황이 경쟁 구도를 바꿀 수 있으므로 반드시 확인해.
- evidence의 source_year는 반드시 기재해.
"""


# ────────────────────────────────────────────────────────
# 에이전트 본체
# ────────────────────────────────────────────────────────

def competitor_comparison_agent(state: AgentState) -> AgentState:
    """웹 검색 + LLM 기반 경쟁사 분석을 수행한다."""
    company = get_current_company(state)
    company_name = company["company_name"]
    tech_summary = company.get("tech_summary", "")
    market_summary = company.get("market_summary", "")

    # 1) 웹 검색 수행
    search_queries = [
        f"{company_name} AI chip competitors comparison 2025 2026",
        f"{company_name} vs NVIDIA Groq Tenstorrent NPU",
        f"AI inference chip competitive landscape startup 2025",
        f"{company_name} semiconductor funding M&A acquisition",
        f"CUDA alternative AI chip software ecosystem 2025",
    ]
    add_log(state, "competitor_compare", f"웹 검색 시작: {company_name}")
    search_results = web_search(search_queries)
    add_log(state, "competitor_compare", f"검색 결과 {len(search_results)}건 수집")

    # 2) LLM 호출 (PDF 원본 청크도 함께 전달)
    user_prompt = _build_user_prompt(
        company_name=company_name,
        question=state["question"],
        tech_summary=tech_summary,
        market_summary=market_summary,
        search_results=search_results,
        retrieved_docs=company.get("retrieved_docs", []),
    )

    result = call_llm_json(SYSTEM_PROMPT, user_prompt)

    # 3) State에 기록
    if "error" in result:
        company["competitor_summary"] = f"LLM 응답 파싱 실패: {result.get('error', '')}"
        company["competitor_score"] = 0.50
        add_log(state, "competitor_compare", f"{company_name} LLM 파싱 실패, 기본값 사용")
    else:
        company["competitor_summary"] = result.get("competition_summary", "")
        # competition_score: 0~10 → 0.0~1.0 정규화
        raw_score = result.get("competition_score", 5)
        company["competitor_score"] = round(min(max(raw_score / 10.0, 0.0), 1.0), 2)

        # evidence를 state에 저장 (보고서 REFERENCE용)
        evidence = result.get("evidence", [])
        if evidence:
            company.setdefault("competitor_evidence", evidence)

        add_log(
            state, "competitor_compare",
            f"{company_name} competitor_score={company['competitor_score']} "
            f"(raw={raw_score}/10, status={result.get('competitor_status', 'N/A')})"
        )

    return state
