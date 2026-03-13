from __future__ import annotations

import argparse

from agents import (
    competitor_comparison_agent,
    investment_decision_agent,
    investment_risk_agent,
    market_eval_agent,
    paper_retrieval_agent,
    proof_check_agent,
    report_writer_agent,
    tech_summary_agent,
)
from config import DATA_DIR, DEFAULT_COMPANIES, EMBEDDING_MODEL, FALLBACK_FILES, MAX_RETRIEVAL_ATTEMPTS
from rag import ProjectAnalysisModel, ProjectPdfPaperRetriever
from state import create_initial_state, ensure_company_slot, get_current_company


def run_pipeline(question: str, target_companies: list[str]) -> dict:
    state = create_initial_state(question, target_companies)
    retriever = ProjectPdfPaperRetriever(
        data_dir=DATA_DIR,
        model_name=EMBEDDING_MODEL,
        fallback_files=FALLBACK_FILES,
    )
    model = ProjectAnalysisModel()

    for company_id in target_companies:
        state["current_company_id"] = company_id
        ensure_company_slot(state, company_id)

        while True:
            state = paper_retrieval_agent(state, retriever)
            state = proof_check_agent(state)

            company = get_current_company(state)
            if company["proof_status"] == "verified":
                break
            if company["retrieval_attempts"] >= MAX_RETRIEVAL_ATTEMPTS:
                company["proof_notes"].append("max retrieval attempts reached")
                company["retrieval_status"] = "failed_after_retry"
                break

        state = tech_summary_agent(state, model)
        state = market_eval_agent(state)          # 웹 검색 + LLM
        state = competitor_comparison_agent(state) # 웹 검색 + LLM
        state = investment_risk_agent(state)
        state = investment_decision_agent(state)
        state["current_index"] += 1

    state["should_finalize"] = True
    state["stop_reason"] = "all target companies analyzed"
    state = report_writer_agent(state)
    return state


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the multi-agent semiconductor company evaluator")
    parser.add_argument(
        "--question",
        default="Rebellions, FuriosaAI, Mobilint 세 기업의 기술 경쟁력과 투자 우선순위를 비교해줘",
        help="User question for the report",
    )
    parser.add_argument(
        "--companies",
        nargs="+",
        default=DEFAULT_COMPANIES,
        help="Target companies to evaluate",
    )
    parser.add_argument(
        "--output",
        default="output/investment_report.pdf",
        help="Output PDF file path",
    )
    parser.add_argument(
        "--no-pdf",
        action="store_true",
        help="Skip PDF generation, print markdown only",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = run_pipeline(question=args.question, target_companies=args.companies)
    print(state["final_report"])

    if not args.no_pdf:
        from pdf_exporter import markdown_to_pdf
        pdf_path = markdown_to_pdf(state["final_report"], args.output)
        print(f"\n{'='*50}")
        print(f"PDF 보고서 생성 완료: {pdf_path}")
        print(f"{'='*50}")


if __name__ == "__main__":
    main()
