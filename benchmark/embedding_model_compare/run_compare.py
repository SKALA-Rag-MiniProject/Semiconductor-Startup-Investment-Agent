from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import yaml
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rag.embedder import compact_text, split_chunks


@dataclass
class RetrievalItem:
    source: str
    page: int
    score: float
    text: str = ""


def _pick_torch_device() -> str:
    try:
        import torch
    except Exception:
        return "cpu"
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _unique_by_source(results: List[RetrievalItem], top_k: int) -> List[RetrievalItem]:
    unique: List[RetrievalItem] = []
    seen = set()
    for row in results:
        if row.source in seen:
            continue
        seen.add(row.source)
        unique.append(row)
        if len(unique) >= top_k:
            break
    return unique


class TextEmbeddingRetriever:
    def __init__(self, model_name: str, data_dir: Path) -> None:
        self.model_name = model_name
        self.data_dir = data_dir
        self.model = SentenceTransformer(model_name, device="cpu", trust_remote_code=True)
        self.items: List[RetrievalItem] = []
        self.embeddings: np.ndarray | None = None

    def build_index(self) -> None:
        raw_texts: List[str] = []
        for pdf in sorted(self.data_dir.glob("*.pdf")):
            reader = PdfReader(str(pdf))
            for page_idx, page in enumerate(reader.pages, start=1):
                text = page.extract_text() or ""
                for chunk in split_chunks(text):
                    cleaned = compact_text(chunk)
                    if not cleaned:
                        continue
                    self.items.append(RetrievalItem(source=pdf.name, page=page_idx, score=0.0, text=cleaned))
                    raw_texts.append(cleaned)

        if not raw_texts:
            raise RuntimeError(f"No text chunks found in {self.data_dir}")

        vectors = self.model.encode(
            raw_texts,
            batch_size=16,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=True,
        )
        self.embeddings = vectors.astype(np.float32)

    def search(self, query: str, top_k: int) -> List[RetrievalItem]:
        if self.embeddings is None:
            raise RuntimeError("Index is not built")

        q = self.model.encode([query], convert_to_numpy=True, normalize_embeddings=True)[0].astype(np.float32)
        scores = self.embeddings @ q
        idxs = np.argsort(-scores)[:top_k]

        out: List[RetrievalItem] = []
        for idx in idxs:
            item = self.items[int(idx)]
            out.append(
                RetrievalItem(
                    source=item.source,
                    page=item.page,
                    score=float(scores[int(idx)]),
                    text=item.text[:180],
                )
            )
        return out


class ColPaliRetriever:
    def __init__(self, data_dir: Path, index_root: Path, device: str = "auto") -> None:
        self.data_dir = data_dir
        self.index_root = index_root
        self.device = device
        self.engine = None

    def build_index(self) -> None:
        try:
            from byaldi import RAGMultiModalModel
        except Exception as exc:
            raise RuntimeError("ColPali requires byaldi. Install with: pip install byaldi") from exc

        device = _pick_torch_device() if self.device == "auto" else self.device
        index_name = "colpali_pdf_index"
        self.index_root.mkdir(parents=True, exist_ok=True)
        index_dir = self.index_root / index_name

        if index_dir.exists():
            self.engine = RAGMultiModalModel.from_index(
                index_path=index_name,
                index_root=str(self.index_root),
                device=device,
            )
            return

        self.engine = RAGMultiModalModel.from_pretrained("vidore/colpali-v1.2", device=device)
        self.engine.index(
            input_path=str(self.data_dir),
            index_name=index_name,
            store_collection_with_index=True,
            index_root=str(self.index_root),
        )

    def search(self, query: str, top_k: int) -> List[RetrievalItem]:
        if self.engine is None:
            raise RuntimeError("Index is not built")

        results = self.engine.search(query, k=top_k)
        out: List[RetrievalItem] = []

        for row in results:
            source = str(
                row.get("source")
                or row.get("doc_name")
                or row.get("document_name")
                or row.get("pdf_name")
                or row.get("file_name")
                or row.get("path")
                or "unknown"
            )
            page = int(row.get("page_num") or row.get("page") or 0)
            score = float(row.get("score") or 0.0)
            out.append(RetrievalItem(source=Path(source).name, page=page, score=score, text=""))
        return out


def hit_at_k(results: List[RetrievalItem], relevant: set[str], k: int) -> float:
    top = results[:k]
    return 1.0 if any(r.source in relevant for r in top) else 0.0


def mrr_at_k(results: List[RetrievalItem], relevant: set[str], k: int) -> float:
    for i, row in enumerate(results[:k], start=1):
        if row.source in relevant:
            return 1.0 / i
    return 0.0


def ndcg_at_k(results: List[RetrievalItem], relevant: set[str], k: int) -> float:
    dcg = 0.0
    for i, row in enumerate(results[:k], start=1):
        rel = 1.0 if row.source in relevant else 0.0
        dcg += rel / math.log2(i + 1.0)

    ideal_rels = [1.0] * min(len(relevant), k)
    idcg = 0.0
    for i, rel in enumerate(ideal_rels, start=1):
        idcg += rel / math.log2(i + 1.0)

    if idcg == 0:
        return 0.0
    return dcg / idcg


def evaluate_model(name: str, retriever, eval_queries: List[dict], top_k: int) -> Dict:
    rows = []
    for q in tqdm(eval_queries, desc=f"Evaluating {name}"):
        query = q["query"]
        relevant = set(q["relevant_sources"])
        retrieved = retriever.search(query, top_k=top_k * 4)
        unique_retrieved = _unique_by_source(retrieved, top_k)
        rows.append(
            {
                "query_id": q["id"],
                "query": query,
                "relevant_sources": sorted(relevant),
                "retrieved": [
                    {
                        "source": r.source,
                        "page": r.page,
                        "score": round(r.score, 6),
                        "text_preview": r.text,
                    }
                    for r in retrieved
                ],
                "retrieved_unique_sources": [
                    {
                        "source": r.source,
                        "page": r.page,
                        "score": round(r.score, 6),
                    }
                    for r in unique_retrieved
                ],
                "hit_at_k": hit_at_k(unique_retrieved, relevant, top_k),
                "mrr_at_k": mrr_at_k(unique_retrieved, relevant, top_k),
                "ndcg_at_k": ndcg_at_k(unique_retrieved, relevant, top_k),
            }
        )

    return {
        "model": name,
        "top_k": top_k,
        "num_queries": len(rows),
        "metrics": {
            "hit_at_k": round(float(np.mean([r["hit_at_k"] for r in rows])) if rows else 0.0, 4),
            "mrr_at_k": round(float(np.mean([r["mrr_at_k"] for r in rows])) if rows else 0.0, 4),
            "ndcg_at_k": round(float(np.mean([r["ndcg_at_k"] for r in rows])) if rows else 0.0, 4),
        },
        "details": rows,
    }


def write_markdown(results: Dict, out_path: Path) -> None:
    lines = [
        "# Embedding Model Comparison",
        "",
        f"- Generated at: {results['generated_at']}",
        f"- Data dir: `{results['data_dir']}`",
        f"- Eval file: `{results['eval_file']}`",
        f"- Top-K: `{results['top_k']}`",
        "",
        "## Summary",
        "",
        "| Model | Hit@K | MRR@K | nDCG@K | Status |",
        "|---|---:|---:|---:|---|",
    ]

    for row in results["models"]:
        if row.get("status") == "ok":
            m = row["metrics"]
            lines.append(
                f"| {row['model']} | {m['hit_at_k']} | {m['mrr_at_k']} | {m['ndcg_at_k']} | ok |"
            )
        else:
            lines.append(f"| {row['model']} | - | - | - | skipped: {row.get('error', '')} |")

    lines.append("")
    lines.append("## Per-Model Details")
    lines.append("")
    for row in results["models"]:
        lines.append(f"### {row['model']}")
        if row.get("status") != "ok":
            lines.append(f"- status: skipped")
            lines.append(f"- reason: `{row.get('error', 'unknown')}`")
            lines.append("")
            continue
        for d in row["details"]:
            lines.append(f"- Query `{d['query_id']}`: `{d['query']}`")
            lines.append(
                f"  -> hit={d['hit_at_k']}, mrr={round(d['mrr_at_k'], 4)}, ndcg={round(d['ndcg_at_k'], 4)}"
            )
        lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare ColPali / Jina v3 / BGE-M3 retrieval quality")
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--eval-file", type=Path, required=True)
    parser.add_argument("--models", type=str, default="jina,bge,colpali")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark/embedding_model_compare/results"))
    parser.add_argument("--colpali-device", type=str, default="auto", choices=["auto", "cpu", "mps", "cuda"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    selected = [m.strip().lower() for m in args.models.split(",") if m.strip()]
    eval_data = yaml.safe_load(args.eval_file.read_text(encoding="utf-8"))
    queries = eval_data.get("queries", [])
    if not queries:
        raise RuntimeError(f"No queries found in {args.eval_file}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    run_at = datetime.now().strftime("%Y%m%d_%H%M%S")

    model_rows: List[Dict] = []

    for model_key in selected:
        try:
            if model_key == "jina":
                retriever = TextEmbeddingRetriever("jinaai/jina-embeddings-v3", args.data_dir)
                retriever.build_index()
                result = evaluate_model("jinaai/jina-embeddings-v3", retriever, queries, args.top_k)
                result["status"] = "ok"
                model_rows.append(result)
            elif model_key == "bge":
                retriever = TextEmbeddingRetriever("BAAI/bge-m3", args.data_dir)
                retriever.build_index()
                result = evaluate_model("BAAI/bge-m3", retriever, queries, args.top_k)
                result["status"] = "ok"
                model_rows.append(result)
            elif model_key == "colpali":
                retriever = ColPaliRetriever(
                    data_dir=args.data_dir,
                    index_root=Path("benchmark/embedding_model_compare/.colpali_index"),
                    device=args.colpali_device,
                )
                retriever.build_index()
                result = evaluate_model("vidore/colpali-v1.2", retriever, queries, args.top_k)
                result["status"] = "ok"
                model_rows.append(result)
            else:
                model_rows.append(
                    {
                        "model": model_key,
                        "status": "skipped",
                        "error": "Unknown model key. Use one of: jina,bge,colpali",
                    }
                )
        except Exception as exc:
            model_rows.append({"model": model_key, "status": "skipped", "error": str(exc)})

    payload = {
        "generated_at": datetime.now().isoformat(),
        "data_dir": str(args.data_dir),
        "eval_file": str(args.eval_file),
        "top_k": args.top_k,
        "models": model_rows,
    }

    json_path = args.output_dir / f"compare_{run_at}.json"
    md_path = args.output_dir / f"compare_{run_at}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(payload, md_path)

    print(f"[DONE] JSON: {json_path}")
    print(f"[DONE] Markdown: {md_path}")


if __name__ == "__main__":
    main()
