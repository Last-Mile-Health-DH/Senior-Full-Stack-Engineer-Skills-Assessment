from fastapi import APIRouter, Depends

from backend.deps import get_rag_engine
from backend.rag.rag_builder import RAGPgVector
from backend.schemas import ChatRequest, ChatResponse
from backend.services.chat import answer_with_sources

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    engine: RAGPgVector = Depends(get_rag_engine),
) -> ChatResponse:
    return answer_with_sources(engine, request.question, request.num_results)
