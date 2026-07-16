from datetime import datetime

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    database: str
    embedder_loaded: bool


class UploadResponse(BaseModel):
    doc_name: str
    chunks_ingested: int


class DocumentFile(BaseModel):
    id: int
    doc_name: str
    file_size: int
    page_count: int | None
    file_type: str
    created_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentFile]


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    num_results: int = Field(default=5, ge=1, le=20)


class SourceChunk(BaseModel):
    doc_name: str
    similarity: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]
