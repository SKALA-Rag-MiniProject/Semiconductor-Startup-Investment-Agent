"""프로젝트 전역 설정값.

가중치, 임계값, 경로, 에이전트 파라미터 등을 한 곳에서 관리한다.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

# ── LLM / 웹 검색 ────────────────────────────────────
OPENAI_MODEL = "gpt-4o-mini"          # 시장성·경쟁사 에이전트용
OPENAI_TEMPERATURE = 0.2
OPENAI_MAX_TOKENS = 4096
WEB_SEARCH_MAX_RESULTS = 8           # DuckDuckGo 검색 건수
ENV_FILE = Path.home() / "key.env"   # API 키 파일

# ── 경로 ──────────────────────────────────────────────
DATA_DIR = Path("data")
FALLBACK_FILES: List[str] = ["NPU_basic.pdf"]
EMBEDDING_MODEL = "BAAI/bge-m3"

# ── 청킹 ──────────────────────────────────────────────
CHUNK_SIZE = 900
CHUNK_OVERLAP = 150

# ── 검색 ──────────────────────────────────────────────
DEFAULT_TOP_K = 5
MAX_RETRIEVAL_ATTEMPTS = 2
COMPANY_NAME_BOOST = 0.20
FILE_HINT_BOOST = 0.12
FALLBACK_BOOST = 0.03

# ── 근거 검증 ─────────────────────────────────────────
PROOF_RELEVANCE_THRESHOLD = 0.55

# ── 리스크 에이전트 ───────────────────────────────────
RISK_BASE_SCORE = 0.35
RISK_PROOF_PENALTY = 0.20
RISK_MARKET_PENALTY = 0.15
RISK_COMPETITOR_PENALTY = 0.15
RISK_TECH_PENALTY = 0.10
MARKET_SCORE_THRESHOLD = 0.60
COMPETITOR_SCORE_THRESHOLD = 0.55
TECH_SCORE_THRESHOLD = 0.75

# ── 투자 판단 (Scorecard Valuation Method — 반도체 스타트업 보정) ──
SCORECARD_WEIGHTS: Dict[str, float] = {
    "창업자/팀": 0.30,
    "시장성": 0.25,
    "제품/기술력": 0.15,
    "경쟁 우위": 0.10,
    "실적": 0.10,
    "투자조건": 0.10,
}
INVEST_THRESHOLD = 60          # 60점 이상 → invest
HOLD_THRESHOLD = 60            # 60점 미만 → hold

# ── 등급 기준 ──
GRADE_THRESHOLDS = [
    (90, "A"),
    (80, "B"),
    (70, "C"),
    (60, "D"),
]
GRADE_DEFAULT = "보류"

# ── 판단 라벨/색상 기준 ──
JUDGEMENT_THRESHOLDS = [
    (90, "우수", "green"),
    (80, "양호", "blue"),
    (70, "보통", "yellow"),
    (60, "미흡", "orange"),
]
JUDGEMENT_DEFAULT = ("열악", "red")

# ── 레거시 (실행력 관련) ──
EXECUTION_SCORE_HIGH = 0.72
EXECUTION_SCORE_LOW = 0.60
EXECUTION_DOC_THRESHOLD = 2

# ── 기술 평가 루브릭 ──────────────────────────────────
TECH_CRITERIA: Dict[str, Dict[str, Any]] = {
    "기술 독창성": {
        "question": "기존 NPU 대비 구조적 차별성(아키텍처, dataflow, tensor 처리, memory 구조)이 있는가?",
        "keywords": [
            "architecture", "novel", "dataflow", "tensor",
            "memory hierarchy", "systolic", "chiplet", "ucie", "contribution",
        ],
    },
    "구현 성숙도": {
        "question": "실칩/제품/보드/데모/benchmark/SDK 등 구현 근거가 충분한가?",
        "keywords": [
            "product", "chip", "silicon", "tape-out",
            "benchmark", "demo", "sdk", "deployment", "customer",
        ],
    },
    "효율성": {
        "question": "성능-전력-메모리 효율(TOPS/W, latency, bandwidth) 근거가 있는가?",
        "keywords": [
            "tops/w", "performance", "latency", "throughput",
            "bandwidth", "hbm", "power", "efficiency", "data movement",
        ],
    },
    "확장성 / 적용 가능성": {
        "question": "LLM/비전/엣지/서버 등 적용 범위와 확장 가능성이 높은가?",
        "keywords": [
            "llm", "vision", "edge", "server",
            "datacenter", "scalable", "ecosystem", "framework", "workload",
        ],
    },
}

# ── 기업 별칭 / 파일 힌트 ─────────────────────────────
COMPANY_ALIASES: Dict[str, List[str]] = {
    "Rebellions": ["리벨리온", "리벨리온즈", "rebellions", "rebellion"],
    "FuriosaAI": ["퓨리오사", "furiosa", "furiosaai"],
    "Mobilint": ["모빌린트", "mobilint"],
}

FILE_HINTS: Dict[str, List[str]] = {
    "Rebellions": ["libelion", "rebellion"],
    "FuriosaAI": ["furiosa"],
    "Mobilint": ["mobilint"],
}

DEFAULT_COMPANIES: List[str] = ["Rebellions", "FuriosaAI", "Mobilint"]
