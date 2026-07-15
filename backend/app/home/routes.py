"""
This module contains FastAPI routes for Home page
"""

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import text

from app.database import async_session

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home():
    """Project status and service entry page."""
    return """
    <html>
        <head>
            <title>Last Mile Health RAG Platform</title>
            <style>
                body { font-family: Arial, Helvetica, sans-serif; max-width: 940px; margin: 48px auto; padding: 0 24px; color: #1f2933; line-height: 1.6; }
                h1 { font-size: 2rem; font-weight: 700; margin-bottom: 8px; }
                h2 { font-size: 1.1rem; font-weight: 700; margin-top: 32px; margin-bottom: 8px; color: #0f766e; }
                p.subtitle { color: #52606d; font-size: 1rem; margin-top: 4px; }
                .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-top: 16px; }
                .card { border: 1px solid #d9e2ec; border-radius: 8px; padding: 16px; background: #fff; }
                .card strong { display: block; margin-bottom: 4px; }
                code { background: #f5f7fa; border: 1px solid #d9e2ec; padding: 2px 5px; border-radius: 4px; }
                ul { padding-left: 20px; margin: 8px 0; }
                li { margin-bottom: 6px; }
                a { color: #0f766e; }
            </style>
        </head>
        <body>
            <h1>Last Mile Health RAG Platform</h1>
            <p class="subtitle">FastAPI backend for PDF upload, ingestion-worker indexing, PostgreSQL/pgvector retrieval, grounded chat responses, guardrails, scheduled grading, and gold-standard regression evaluation.</p>

            <h2>Service Links</h2>
            <div class="grid">
                <div class="card">
                    <strong>Backend health</strong>
                    <a href="/health">/health</a>
                </div>
                <div class="card">
                    <strong>OpenAPI docs</strong>
                    <a href="/docs">/docs</a>
                </div>
                <div class="card">
                    <strong>Document API</strong>
                    <code>/api/v1/documents</code>
                </div>
                <div class="card">
                    <strong>Chat API</strong>
                    <code>/api/v1/chat</code>
                </div>
            </div>

            <h2>Implemented Backend Capabilities</h2>
            <ul>
                <li>PDF upload validation, content-hash deduplication, and visible background enqueueing of the ingestion worker for OCR/rasterization, chunking, and pgvector indexing.</li>
                <li>Hybrid retrieval, local CrossEncoder reranking, gated query expansion, exact/semantic caches, and audit logging.</li>
                <li>JWT document access, rate limiting, CORS/security middleware, structured source citations, output filtering, and exact clinical numeric grounding.</li>
                <li>Scheduled cache hygiene, response grading, anomaly detection, and gold-standard evaluation guarded by PostgreSQL advisory locks.</li>
            </ul>

            <h2>Reviewer Notes</h2>
            <ul>
                <li>The Chainlit container at <a href="http://localhost:8000">localhost:8000</a> calls <code>/api/v1/chat</code> and renders answer-level Chicago-style citation notes from backend citation metadata.</li>
                <li>The Next.js document manager at <a href="http://localhost:3000/documents">localhost:3000/documents</a> uploads PDFs and polls until ingestion changes status.</li>
                <li>Gold-standard score floors remain trust-gated until the corpus PDFs are fetched, checksums are pinned, documents are indexed, and expected answers are human-verified.</li>
            </ul>
        </body>
    </html>
    """


@router.get("/health")
async def health() -> JSONResponse:
    """Return backend/database health for Docker and load-balancer checks."""
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "unavailable", "error": str(exc)},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})
