from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    database: str
    embedder_loaded: bool


class UploadResponse(BaseModel):
    doc_name: str
    chunks_ingested: int


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    num_results: int = Field(default=5, ge=1, le=20)


class SourceChunk(BaseModel):
    doc_name: str
    similarity: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
