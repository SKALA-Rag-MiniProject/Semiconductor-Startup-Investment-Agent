from state import AgentState, add_log, get_current_company
from rag import AnalysisModel


def tech_summary_agent(state: AgentState, model: AnalysisModel) -> AgentState:
    company = get_current_company(state)
    result = model.summarize(
        task="technology",
        company=company["company_name"],
        docs=company["retrieved_docs"],
        question=state["question"],
    )
    company["tech_summary"] = result["summary"]
    company["tech_score"] = result["score"]
    company["tech_rubric"] = result.get("criteria", {})
    add_log(state, "tech_summary", f"{company['company_name']} tech_score={result['score']}")
    return state
