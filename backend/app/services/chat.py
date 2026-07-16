from app.rag.rag_builder import RAGPgVector
from app.schemas import ChatResponse, SourceChunk


def answer_with_sources(engine: RAGPgVector, question: str, num_results: int) -> ChatResponse:
    results = engine.search(question, num_results=num_results)
    prompt = engine.build_prompt(question, results)
    answer = engine.llm(prompt)

    return ChatResponse(
        answer=answer,
        sources=[
            SourceChunk(doc_name=result["doc_name"], similarity=result["similarity"])
            for result in results
        ],
    )
