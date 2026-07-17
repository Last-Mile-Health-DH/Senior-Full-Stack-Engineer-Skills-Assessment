"""SQLAlchemy model declarations for the RAG persistence schema."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    Boolean,
    CHAR,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    SmallInteger,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

JSONDict = dict[str, str]


class Vector(UserDefinedType[object]):
    """Minimal SQLAlchemy type for pgvector columns."""

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **kw: object) -> str:
        return f"VECTOR({self.dimension})"


class TSVector(UserDefinedType[object]):
    """Minimal SQLAlchemy type for PostgreSQL tsvector columns."""

    cache_ok = True

    def get_col_spec(self, **kw: object) -> str:
        return "TSVECTOR"


class Base(DeclarativeBase):
    """Base class for SQLAlchemy models.

    NB: https://alembic.sqlalchemy.org/en/latest/naming.html#the-importance-of-naming-constraints
    """  # noqa: E501

    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'processing'"))
    page_count: Mapped[int | None] = mapped_column(Integer)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))

    chunks: Mapped[list[Chunk]] = relationship(back_populates="document", cascade="all, delete-orphan")
    page_images: Mapped[list[PageImage]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_tsv: Mapped[object] = mapped_column(
        TSVector(),
        Computed("to_tsvector('english'::regconfig, content)", persisted=True),
    )
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    section_path: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[object | None] = mapped_column(Vector(1536))
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")

    __table_args__ = (
        Index("chunks_embedding_hnsw_idx", "embedding", postgresql_using="hnsw", postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("chunks_tsv_idx", "content_tsv", postgresql_using="gin"),
        Index("chunks_document_id_idx", "document_id"),
    )


class PageImage(Base):
    __tablename__ = "page_images"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_ref: Mapped[str] = mapped_column(Text, nullable=False)
    has_table: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    has_figure: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="page_images")

    __table_args__ = (
        UniqueConstraint("document_id", "page_number", name="uq_page_images_document_id_page_number"),
        Index("page_images_document_id_idx", "document_id"),
    )


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    user_ref: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    messages: Mapped[list[ChatMessage]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_chunk_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    session: Mapped[ChatSession] = relationship(back_populates="messages")

    __table_args__ = (Index("chat_messages_session_idx", "session_id", "created_at"),)


class ExactCache(Base):
    __tablename__ = "exact_cache"

    query_hash: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source_doc_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SemanticCache(Base):
    __tablename__ = "semantic_cache"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    query_embedding: Mapped[object] = mapped_column(Vector(1536), nullable=False)
    representative_query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    source_doc_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    hit_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("semantic_cache_embedding_idx", "query_embedding", postgresql_using="hnsw", postgresql_ops={"query_embedding": "vector_cosine_ops"}),
        Index("semantic_cache_last_used_idx", "last_used_at"),
    )


class QueryAuditLog(Base):
    __tablename__ = "query_audit_log"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chat_sessions.id"))
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    cache_status: Mapped[str | None] = mapped_column(Text)
    cost_category: Mapped[str | None] = mapped_column(Text)
    retrieved_chunk_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(PGUUID(as_uuid=True)))
    reranked: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    retrieval_mode: Mapped[str | None] = mapped_column(Text)
    generation_model: Mapped[str | None] = mapped_column(Text)
    grounded: Mapped[bool | None] = mapped_column(Boolean)
    input_validation_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'passed'"))
    output_filter_status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'passed'"))
    output_filter_reason: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    token_input: Mapped[int | None] = mapped_column(Integer)
    token_output: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(10, 6))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index(
            "query_audit_log_idempotency_key_idx",
            "idempotency_key",
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )


class AgentTraceLog(Base):
    __tablename__ = "agent_trace_log"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    agent_name: Mapped[str] = mapped_column(Text, nullable=False)
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    session_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("chat_sessions.id"))
    query_audit_log_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("query_audit_log.id"))
    document_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("documents.id"))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        Index("agent_trace_log_session_idx", "session_id"),
        Index("agent_trace_log_document_idx", "document_id"),
    )


class ResponseGrade(Base):
    __tablename__ = "response_grade"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    query_audit_log_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("query_audit_log.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    grounding_check_passed: Mapped[bool | None] = mapped_column(Boolean)
    judge_score: Mapped[int | None] = mapped_column(SmallInteger)
    judge_rationale: Mapped[str | None] = mapped_column(Text)
    sampled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    graded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (Index("response_grade_query_audit_log_idx", "query_audit_log_id"),)


class AnomalyFlag(Base):
    __tablename__ = "anomaly_flag"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    metric_name: Mapped[str] = mapped_column(Text, nullable=False)
    hour_of_day: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    observed_value: Mapped[Decimal | None] = mapped_column(Numeric)
    baseline_mean: Mapped[Decimal | None] = mapped_column(Numeric)
    baseline_stddev: Mapped[Decimal | None] = mapped_column(Numeric)
    z_score: Mapped[Decimal | None] = mapped_column(Numeric)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint("hour_of_day BETWEEN 0 AND 23", name="hour_of_day_range"),
        Index("anomaly_flag_metric_idx", "metric_name", "created_at"),
    )
