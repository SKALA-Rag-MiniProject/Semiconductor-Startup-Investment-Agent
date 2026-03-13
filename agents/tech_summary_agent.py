from __future__ import annotations

from typing import Any, Dict, List

from config import TECH_CRITERIA
from llm_client import call_llm_json, web_search
from rag import AnalysisModel
from rag.scoring import summarize_technical_capability
from state import AgentState, RetrievedDoc, add_log, get_current_company


SYSTEM_PROMPT = """\
당신은 반도체 스타트업 투자 평가를 위한 기술 실사(Technical DD) 에이전트다.

목표:
- 제공된 문서 근거만 사용해 기술력을 평가한다.
- 4개 기준(기술 독창성, 구현 성숙도, 효율성, 확장성/적용 가능성)을 각각 1~5점으로 채점한다.
- 하드웨어 정량지표(TOPS/W, latency, throughput, power, bandwidth, process node)를 우선적으로 찾아 요약에 반영한다.
- 전체 tech_score(1~5)를 산출하고 간결한 기술 요약을 작성한다.

행동 원칙:
1. 제공된 문서 근거 밖의 사실을 추가하지 않는다.
2. 모르는 항목은 추정하지 말고 근거 부족으로 표시한다.
3. 과장 표현(압도적, 혁신적 등)을 피하고 투자자 관점으로 작성한다.
4. 점수는 보수적으로 부여한다.
5. 각 기준별로 최소 1개 이상의 evidence를 제시한다.
6. 정량지표가 없다고 자동 감점하지 말고, 대신 confidence를 낮춰라.
7. 하드웨어 정량지표 근거가 부족하면, 어떤 웹 자료를 추가로 찾아야 하는지 구체적인 탐색 계획을 제시한다.
8. 웹 탐색 계획은 공식/1차 출처 우선으로 제시한다(회사 데이터시트, 제품 페이지, 공식 발표자료, 벤치마크 공식 제출 페이지).

출력 규칙:
- 반드시 JSON만 출력한다.
- 점수는 숫자(정수/실수)로 출력한다.
"""


def _build_user_prompt(
    company_name: str,
    question: str,
    docs: List[RetrievedDoc],
    web_results: List[Dict[str, str]] | None = None,
) -> str:
    doc_lines: List[str] = []
    for i, doc in enumerate(docs[:5], 1):
        source = doc.get("source", "unknown")
        page = doc.get("metadata", {}).get("page", "?")
        sim = doc.get("score", 0.0)
        text = (doc.get("text", "") or "")[:1200]
        doc_lines.append(f"[문서{i}] {source}:{page} (sim={sim})\n{text}")
    doc_section = "\n\n".join(doc_lines) if doc_lines else "(검색 문서 없음)"

    web_section = "(웹 탐색 결과 없음)"
    if web_results:
        rows = []
        for r in web_results[:12]:
            title = r.get("title", "")
            url = r.get("url", "")
            snippet = r.get("snippet", "")
            rows.append(f"- [{title}]({url}): {snippet}")
        web_section = "\n".join(rows) if rows else "(웹 탐색 결과 없음)"

    return f"""\
[대상 기업]
- company: {company_name}

[사용자 질문]
{question}

[검색된 문서 근거]
{doc_section}

[웹 탐색 근거 (정량지표 보강용)]
{web_section}

[평가 기준]
1) 기술 독창성
2) 구현 성숙도
3) 효율성
4) 확장성 / 적용 가능성

[출력 형식]
{{
  "tech_summary": "2~4문장 요약",
  "tech_score": 0,
  "tech_confidence": "high / medium / low",
  "quant_metrics": {{
    "tops": [{{"value": "", "unit": "", "source": "source:page"}}],
    "tops_per_watt": [{{"value": "", "unit": "", "source": "source:page"}}],
    "latency": [{{"value": "", "unit": "", "source": "source:page"}}],
    "throughput": [{{"value": "", "unit": "", "source": "source:page"}}],
    "power": [{{"value": "", "unit": "", "source": "source:page"}}],
    "memory_bandwidth": [{{"value": "", "unit": "", "source": "source:page"}}],
    "process_node": [{{"value": "", "unit": "nm", "source": "source:page"}}],
    "note": "정량 지표 요약. 없으면 근거 부족이라고 명시"
  }},
  "quant_evidence_status": "sufficient / insufficient",
  "web_search_plan": {{
    "needed": true,
    "reason": "왜 추가 탐색이 필요한지",
    "priority_sources": [
      "company official product page",
      "company datasheet or whitepaper",
      "official benchmark submission"
    ],
    "suggested_queries": [
      "회사명 제품명 TOPS/W datasheet",
      "회사명 제품명 latency throughput power",
      "회사명 process node foundry"
    ]
  }},
  "criteria": {{
    "기술 독창성": {{
      "score": 0,
      "reason": "한 문장",
      "evidence": ["source:page 근거 요약"]
    }},
    "구현 성숙도": {{
      "score": 0,
      "reason": "한 문장",
      "evidence": ["source:page 근거 요약"]
    }},
    "효율성": {{
      "score": 0,
      "reason": "한 문장",
      "evidence": ["source:page 근거 요약"]
    }},
    "확장성 / 적용 가능성": {{
      "score": 0,
      "reason": "한 문장",
      "evidence": ["source:page 근거 요약"]
    }}
  }}
}}
"""


def _to_rubric(criteria: Dict[str, Any], fallback: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, cfg in TECH_CRITERIA.items():
        fallback_row = fallback.get("criteria", {}).get(name, {})
        row = criteria.get(name, {}) if isinstance(criteria, dict) else {}
        raw_score = row.get("score", fallback_row.get("score", 2))
        try:
            score = int(round(float(raw_score)))
        except (TypeError, ValueError):
            score = int(fallback_row.get("score", 2))
        score = max(1, min(5, score))
        evidence = row.get("evidence", fallback_row.get("evidence", []))
        if not isinstance(evidence, list):
            evidence = [str(evidence)]
        out[name] = {
            "score": score,
            "question": cfg["question"],
            "reason": row.get("reason", ""),
            "evidence": evidence,
        }
    return out


def _score_from_rubric(rubric: Dict[str, Any], fallback_avg_5: float) -> float:
    scores: List[int] = []
    for name in TECH_CRITERIA.keys():
        row = rubric.get(name, {})
        raw = row.get("score")
        try:
            score = int(round(float(raw)))
        except (TypeError, ValueError):
            continue
        scores.append(max(1, min(5, score)))
    if not scores:
        return max(1.0, min(5.0, float(fallback_avg_5)))
    return round(sum(scores) / len(scores), 2)


def _normalize_confidence(raw: Any) -> str:
    val = str(raw or "").strip().lower()
    if val in {"high", "medium", "low"}:
        return val
    return "medium"


def _normalize_quant_metrics(payload: Any) -> Dict[str, Any]:
    default = {
        "tops": [],
        "tops_per_watt": [],
        "latency": [],
        "throughput": [],
        "power": [],
        "memory_bandwidth": [],
        "process_node": [],
        "note": "근거 부족",
    }
    if not isinstance(payload, dict):
        return default
    out = dict(default)
    for key in default.keys():
        if key in payload:
            out[key] = payload[key]
    return out


def _has_quant_evidence(quant: Dict[str, Any]) -> bool:
    metric_keys = [
        "tops",
        "tops_per_watt",
        "latency",
        "throughput",
        "power",
        "memory_bandwidth",
        "process_node",
    ]
    for key in metric_keys:
        rows = quant.get(key, [])
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            value = str(row.get("value", "")).strip()
            source = str(row.get("source", "")).strip()
            if value and source:
                return True
    return False


def _build_web_queries(company_name: str, llm_result: Dict[str, Any]) -> List[str]:
    defaults = [
        f"{company_name} NPU TOPS/W datasheet",
        f"{company_name} NPU latency throughput power benchmark",
        f"{company_name} AI accelerator process node foundry",
        f"{company_name} whitepaper performance",
    ]
    plan = llm_result.get("web_search_plan", {}) if isinstance(llm_result, dict) else {}
    suggested = plan.get("suggested_queries", []) if isinstance(plan, dict) else []

    merged: List[str] = []
    for q in [*suggested, *defaults]:
        if not isinstance(q, str):
            continue
        q = q.strip()
        if not q or q in merged:
            continue
        merged.append(q)
    return merged[:6]


def tech_summary_agent(state: AgentState, model: AnalysisModel) -> AgentState:
    company = get_current_company(state)
    company_name = company["company_name"]
    docs = company.get("retrieved_docs", [])

    # LLM 실패 시에도 파이프라인을 유지하기 위한 규칙 기반 폴백
    fallback = summarize_technical_capability(company=company_name, docs=docs)

    try:
        user_prompt = _build_user_prompt(company_name=company_name, question=state["question"], docs=docs)
        llm_result = call_llm_json(SYSTEM_PROMPT, user_prompt)
        if "error" in llm_result:
            raise RuntimeError(llm_result.get("error", "unknown llm json parse error"))

        quant_metrics = _normalize_quant_metrics(llm_result.get("quant_metrics"))
        quant_status = str(llm_result.get("quant_evidence_status", "")).strip().lower()
        insufficient = (quant_status != "sufficient") or (not _has_quant_evidence(quant_metrics))

        if insufficient:
            queries = _build_web_queries(company_name, llm_result)
            if queries:
                add_log(state, "tech_summary", f"{company_name} quant metrics insufficient -> web search {len(queries)} queries")
                web_results = web_search(queries, max_results=5)
                user_prompt = _build_user_prompt(
                    company_name=company_name,
                    question=state["question"],
                    docs=docs,
                    web_results=web_results,
                )
                enriched = call_llm_json(SYSTEM_PROMPT, user_prompt)
                if "error" not in enriched:
                    llm_result = enriched

        tech_rubric = _to_rubric(llm_result.get("criteria", {}), fallback)
        tech_score_5 = _score_from_rubric(tech_rubric, fallback["avg_score_5"])
        tech_score = round(max(0.0, min(1.0, tech_score_5 / 5.0)), 2)
        tech_summary = llm_result.get("tech_summary", "") or fallback["summary"]
        tech_confidence = _normalize_confidence(llm_result.get("tech_confidence"))
        quant_metrics = _normalize_quant_metrics(llm_result.get("quant_metrics"))

        company["tech_summary"] = tech_summary
        company["tech_score"] = tech_score
        company["tech_rubric"] = tech_rubric
        company["tech_confidence"] = tech_confidence
        company["tech_quant_metrics"] = quant_metrics
        add_log(
            state,
            "tech_summary",
            f"{company_name} tech_score={tech_score} (LLM, confidence={tech_confidence})",
        )
    except Exception as exc:
        company["tech_summary"] = fallback["summary"]
        company["tech_score"] = fallback["score"]
        company["tech_rubric"] = fallback.get("criteria", {})
        company["tech_confidence"] = "low"
        company["tech_quant_metrics"] = {
            "tops": [],
            "tops_per_watt": [],
            "latency": [],
            "throughput": [],
            "power": [],
            "memory_bandwidth": [],
            "process_node": [],
            "note": "LLM 평가 실패로 규칙 기반 폴백 사용",
        }
        add_log(state, "tech_summary", f"{company_name} tech_score={fallback['score']} (fallback: {exc})")

    return state
