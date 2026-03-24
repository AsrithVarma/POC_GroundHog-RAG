import logging
import time
from collections import defaultdict

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from src.api.auth import create_token, get_current_user, verify_password
from src.api.db import get_connection, put_connection
from src.api.health import check_health
from src.api.middleware.log_sanitizer import install_globally
from src.api.rag import answer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
install_globally()
logger = logging.getLogger(__name__)

RATE_LIMIT_MAX = 30
RATE_LIMIT_WINDOW = 60  # seconds

app = FastAPI(title="GroundHog RAG API", docs_url=None, redoc_url=None)

# CORS — localhost only
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Rate limiter (in-memory, per-user) ---

_rate_store: dict[str, list[float]] = defaultdict(list)


def _check_rate_limit(user_id: str) -> None:
    now = time.monotonic()
    window_start = now - RATE_LIMIT_WINDOW

    hits = _rate_store[user_id]
    _rate_store[user_id] = [t for t in hits if t > window_start]

    if len(_rate_store[user_id]) >= RATE_LIMIT_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded: {RATE_LIMIT_MAX} requests per minute",
        )

    _rate_store[user_id].append(now)


# --- Request models ---


from pydantic import Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=5000)
    top_k: int = Field(default=10, ge=1, le=50)


# --- Endpoints ---


@app.get("/health")
def health():
    return check_health()


@app.post("/auth/login")
def login(body: LoginRequest):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash, access_group, role FROM users WHERE username = %s",
                (body.username,),
            )
            row = cur.fetchone()
    finally:
        conn.rollback()
        put_connection(conn)

    if row is None or not verify_password(body.password, row[1]):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    user_id, _, access_group, role = str(row[0]), row[1], row[2], row[3]
    token = create_token(user_id, body.username, access_group, role)

    logger.info("User authenticated: %s", body.username)
    return {"access_token": token, "token_type": "bearer"}


@app.post("/chat")
def chat(body: ChatRequest, user: dict = Depends(get_current_user)):
    _check_rate_limit(user["user_id"])

    def event_stream():
        for token in answer(
            question=body.question,
            user_id=user["user_id"],
            access_group=user["access_group"],
            top_k=body.top_k,
        ):
            yield f"data: {token}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.get("/documents")
def list_documents(user: dict = Depends(get_current_user)):
    _check_rate_limit(user["user_id"])

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, filename, page_count, ingested_at, access_group
                FROM documents
                WHERE (access_group = %s OR %s IS NULL)
                ORDER BY ingested_at DESC
                """,
                (user["access_group"], user["access_group"]),
            )
            rows = cur.fetchall()
    finally:
        conn.rollback()
        put_connection(conn)

    return [
        {
            "id": str(row[0]),
            "filename": row[1],
            "page_count": row[2],
            "ingested_at": row[3].isoformat() if row[3] else None,
            "access_group": row[4],
        }
        for row in rows
    ]


@app.get("/sources/{chunk_id}")
def get_source(chunk_id: str, user: dict = Depends(get_current_user)):
    _check_rate_limit(user["user_id"])

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    c.id, c.chunk_index, c.page_number, c.created_at,
                    d.id, d.filename, d.page_count, d.ingested_at, d.access_group
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE c.id = %s::uuid
                """,
                (chunk_id,),
            )
            row = cur.fetchone()
    finally:
        conn.rollback()
        put_connection(conn)

    if row is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    # RBAC: check access group
    doc_access_group = row[8]
    if user["access_group"] is not None and doc_access_group != user["access_group"]:
        raise HTTPException(status_code=403, detail="Access denied")

    return {
        "chunk": {
            "id": str(row[0]),
            "chunk_index": row[1],
            "page_number": row[2],
            "created_at": row[3].isoformat() if row[3] else None,
        },
        "document": {
            "id": str(row[4]),
            "filename": row[5],
            "page_count": row[6],
            "ingested_at": row[7].isoformat() if row[7] else None,
            "access_group": row[8],
        },
    }
