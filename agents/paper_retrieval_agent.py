from state import AgentState, add_log, ensure_company_slot
from rag import PaperRetriever
from agents.utils import rewrite_query


def paper_retrieval_agent(state: AgentState, retriever: PaperRetriever) -> AgentState:
    company_id = state["current_company_id"]
    if company_id is None:
        raise ValueError("No current company selected")

    company = ensure_company_slot(state, company_id)
    attempt = company["retrieval_attempts"] + 1
    query = rewrite_query(state["question"], company_id, attempt)
    docs = retriever.search(company=company_id, query=query, top_k=5)

    company["retrieval_query"] = query
    company["retrieval_attempts"] = attempt
    company["retrieved_docs"] = docs
    add_log(state, "retrieval", f"{company_id} attempt={attempt}, docs={len(docs)}")
    return state
