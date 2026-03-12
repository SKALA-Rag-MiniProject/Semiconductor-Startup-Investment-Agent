"""OpenAI LLM 클라이언트 + DuckDuckGo 웹 검색 유틸리티."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

from openai import OpenAI

from config import (
    ENV_FILE,
    OPENAI_MAX_TOKENS,
    OPENAI_MODEL,
    OPENAI_TEMPERATURE,
    WEB_SEARCH_MAX_RESULTS,
)


# ────────────────────────────────────────────────────────
# API 키 로딩
# ────────────────────────────────────────────────────────

def _load_env_file() -> None:
    """~/key.env 파일에서 환경 변수를 로드한다."""
    if os.environ.get("OPEN_AI_KEY"):
        return
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("export ") and "=" in line:
                line = line[len("export "):]
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key.strip(), value)


def get_openai_client() -> OpenAI:
    """OpenAI 클라이언트를 반환한다."""
    _load_env_file()
    api_key = os.environ.get("OPEN_AI_KEY") or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPEN_AI_KEY 또는 OPENAI_API_KEY 환경 변수가 설정되지 않았습니다.")
    return OpenAI(api_key=api_key)


# ────────────────────────────────────────────────────────
# 웹 검색
# ────────────────────────────────────────────────────────

def web_search(queries: List[str], max_results: int = WEB_SEARCH_MAX_RESULTS) -> List[Dict[str, str]]:
    """DuckDuckGo로 여러 쿼리를 검색하고 결과를 합쳐 반환한다.

    Returns:
        [{"title": ..., "url": ..., "snippet": ...}, ...]
    """
    from duckduckgo_search import DDGS

    all_results: List[Dict[str, str]] = []
    seen_urls: set = set()

    with DDGS() as ddgs:
        for query in queries:
            try:
                results = ddgs.text(query, max_results=max_results)
                for r in results:
                    url = r.get("href", "")
                    if url in seen_urls:
                        continue
                    seen_urls.add(url)
                    all_results.append({
                        "title": r.get("title", ""),
                        "url": url,
                        "snippet": r.get("body", ""),
                    })
            except Exception as e:
                all_results.append({
                    "title": f"검색 오류: {query}",
                    "url": "",
                    "snippet": str(e),
                })
    return all_results


# ────────────────────────────────────────────────────────
# LLM 호출
# ────────────────────────────────────────────────────────

def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: str = OPENAI_MODEL,
    temperature: float = OPENAI_TEMPERATURE,
    max_tokens: int = OPENAI_MAX_TOKENS,
) -> str:
    """OpenAI Chat Completion을 호출하고 응답 텍스트를 반환한다."""
    client = get_openai_client()
    response = client.chat.completions.create(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content or ""


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    model: str = OPENAI_MODEL,
    temperature: float = OPENAI_TEMPERATURE,
    max_tokens: int = OPENAI_MAX_TOKENS,
) -> Dict[str, Any]:
    """LLM을 호출하고 JSON 응답을 파싱하여 반환한다."""
    raw = call_llm(system_prompt, user_prompt, model, temperature, max_tokens)

    # JSON 블록 추출 (```json ... ``` 또는 { ... })
    json_match = re.search(r"```json\s*([\s\S]*?)```", raw)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # 첫 번째 { 부터 마지막 } 까지
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1:
            json_str = raw[start:end + 1]
        else:
            return {"error": "JSON 파싱 실패", "raw_response": raw[:500]}

    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return {"error": "JSON 파싱 실패", "raw_response": json_str[:500]}
