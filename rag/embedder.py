from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import List

from config import CHUNK_SIZE, CHUNK_OVERLAP


def compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_chunks(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> List[str]:
    text = compact_text(text)
    if not text:
        return []
    out: List[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        out.append(text[start:end])
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return out


def normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass
class Chunk:
    source: str
    page: int
    text: str
    emb: List[float]


class Embedder:
    def __init__(self, model_name: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception as exc:
            raise RuntimeError("sentence-transformers가 필요합니다. 예: pip install sentence-transformers") from exc
        self.model = SentenceTransformer(model_name, device="cpu")

    def embed(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        if not texts:
            return []
        vectors = self.model.encode(
            texts,
            batch_size=batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return vectors.tolist()
