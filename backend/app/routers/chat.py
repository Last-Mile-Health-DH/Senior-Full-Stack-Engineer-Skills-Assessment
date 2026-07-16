from fastapi import APIRouter, Depends

from app.deps import get_rag_engine
from app.rag.rag_builder import RAGPgVector
from app.schemas import ChatRequest, ChatResponse
from app.services.chat import answer_with_sources

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
def chat(
    request: ChatRequest,
    engine: RAGPgVector = Depends(get_rag_engine),
) -> ChatResponse:
    return answer_with_sources(engine, request.question, request.num_results)
