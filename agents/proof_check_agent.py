from state import AgentState, add_log, get_current_company
from agents.utils import grade_retrieved_docs


def proof_check_agent(state: AgentState) -> AgentState:
    company = get_current_company(state)
    result = grade_retrieved_docs(
        question=state["question"],
        company=company["company_name"],
        docs=company["retrieved_docs"],
    )

    company["proof_status"] = "verified" if result["is_relevant"] else "needs_retry"
    company["retrieval_status"] = company["proof_status"]
    company["proof_notes"].append(
        f"attempt {company['retrieval_attempts']}: relevance_score={result['score']} / {result['reason']}"
    )
    add_log(state, "proof_check", f"{company['company_name']} proof_status={company['proof_status']}")
    return state
