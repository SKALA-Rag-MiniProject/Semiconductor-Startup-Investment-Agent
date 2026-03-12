from __future__ import annotations

from pathlib import Path
from typing import List

from config import (
    COMPANY_ALIASES,
    COMPANY_NAME_BOOST,
    FALLBACK_BOOST,
    FILE_HINT_BOOST,
    FILE_HINTS,
)
from rag.embedder import Chunk, Embedder, compact_text, cosine, normalize, split_chunks
from state import RetrievedDoc


class ProjectPdfPaperRetriever:
    def __init__(
        self,
        data_dir: str | Path,
        model_name: str = "allenai-specter",
        fallback_files: List[str] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.embedder = Embedder(model_name)
        self.chunks: List[Chunk] = []
        self.fallback_files = fallback_files or ["NPU_basic.pdf"]
        self._index_built = False

    def build_index(self) -> None:
        try:
            from pypdf import PdfReader  # type: ignore
        except Exception as exc:
            raise RuntimeError("pypdf가 필요합니다. 예: pip install pypdf") from exc

        pdfs = sorted(self.data_dir.glob("*.pdf"))
        if not pdfs:
            raise RuntimeError(f"PDF 파일이 없습니다: {self.data_dir}")

        metas: List[tuple[str, int, str]] = []
        for pdf in pdfs:
            reader = PdfReader(str(pdf))
            for page_idx, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                for chunk_text in split_chunks(text):
                    metas.append((pdf.name, page_idx, chunk_text))

        embeddings = self.embedder.embed([meta[2] for meta in metas], batch_size=32)
        self.chunks = [
            Chunk(source=source, page=page, text=text, emb=normalize(emb))
            for (source, page, text), emb in zip(metas, embeddings)
        ]
        self._index_built = True

    def _ensure_index(self) -> None:
        if not self._index_built:
            self.build_index()

    def search(self, company: str, query: str, top_k: int = 5) -> List[RetrievedDoc]:
        self._ensure_index()

        aliases = [alias.lower() for alias in COMPANY_ALIASES.get(company, [company])]
        file_hints = [hint.lower() for hint in FILE_HINTS.get(company, [])]
        fallback_files = [name.lower() for name in self.fallback_files]

        query_vec = normalize(self.embedder.embed([query], batch_size=1)[0])
        scored: List[tuple[Chunk, float]] = []
        for chunk in self.chunks:
            score = cosine(query_vec, chunk.emb)
            haystack = f"{chunk.source} {chunk.text}".lower()
            if any(alias in haystack for alias in aliases):
                score += COMPANY_NAME_BOOST
            if any(hint in chunk.source.lower() for hint in file_hints):
                score += FILE_HINT_BOOST
            if any(name in chunk.source.lower() for name in fallback_files):
                score += FALLBACK_BOOST
            scored.append((chunk, score))

        scored.sort(key=lambda item: item[1], reverse=True)
        top = scored[:top_k]
        return [
            {
                "company": company,
                "title": chunk.source,
                "chunk_id": f"{chunk.source}-p{chunk.page}-{idx}",
                "text": chunk.text,
                "score": round(score, 4),
                "source": chunk.source,
                "metadata": {"page": chunk.page},
            }
            for idx, (chunk, score) in enumerate(top, start=1)
        ]
