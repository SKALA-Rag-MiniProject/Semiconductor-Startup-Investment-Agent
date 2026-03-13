# Embedding Model Compare (No Change to Existing Pipeline)

이 폴더는 기존 프로젝트 코드를 수정하지 않고, 아래 3개 후보 임베딩 모델의 검색 성능을 비교하기 위한 독립 벤치마크입니다.

- ColPali (`vidore/colpali-v1.2`, via `byaldi`)
- Jina Embeddings v3 (`jinaai/jina-embeddings-v3`)
- BGE-M3 (`BAAI/bge-m3`)

## What This Benchmark Does

1. `data/*.pdf`를 읽어 검색 코퍼스를 만듭니다.
2. `eval_set.yaml`의 질의를 기준으로 모델별 검색 결과를 생성합니다.
3. 모델별 `Hit@K`, `MRR@K`, `nDCG@K`를 계산합니다.
4. JSON/Markdown 리포트를 `results/`에 저장합니다.

메트릭은 동일 문서의 다중 청크 중복을 제거한 뒤(문서 단위 unique source) 계산합니다.

## Why ColPali Is Treated Separately

ColPali는 PDF 페이지 이미지 기반 멀티모달 검색 모델이고, Jina/BGE는 텍스트 임베딩 모델입니다.
따라서 스크립트는:

- Jina/BGE: 텍스트 청크 검색
- ColPali: 페이지 검색

으로 실행합니다. 동일 쿼리셋으로 비교하되, 방식이 다름을 감안해 결과를 해석해야 합니다.

## Install

가상환경 활성화 후:

```bash
pip install -r benchmark/embedding_model_compare/requirements.txt
```

## Run

기본 실행 (세 모델 모두 시도):

```bash
python benchmark/embedding_model_compare/run_compare.py \
  --data-dir data \
  --eval-file benchmark/embedding_model_compare/eval_set.yaml \
  --models jina,bge,colpali \
  --colpali-device cpu \
  --top-k 5
```

텍스트 모델만 먼저 실행:

```bash
python benchmark/embedding_model_compare/run_compare.py \
  --data-dir data \
  --eval-file benchmark/embedding_model_compare/eval_set.yaml \
  --models jina,bge \
  --top-k 5
```

## Output

- `benchmark/embedding_model_compare/results/compare_*.json`
- `benchmark/embedding_model_compare/results/compare_*.md`

## Notes

- ColPali(`byaldi`)는 설치/초기 인덱싱 비용이 큽니다.
- 로컬 CPU 환경에서는 ColPali가 매우 느릴 수 있습니다.
- 평가 품질은 `eval_set.yaml`의 레이블 품질에 크게 좌우됩니다.
