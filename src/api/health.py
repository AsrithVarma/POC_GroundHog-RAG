import logging
import time

import httpx

from src.api.db import get_connection, put_connection

logger = logging.getLogger(__name__)

_start_time = time.monotonic()

OLLAMA_URL = "http://ollama:11434/api/tags"


def check_health() -> dict:
    """Gather system health. Returns only metadata — no content, queries, or user data."""

    uptime_seconds = round(time.monotonic() - _start_time, 1)

    # --- Database ---
    db_status = "healthy"
    total_documents = 0
    total_chunks = 0
    last_ingestion = None

    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

                cur.execute("SELECT COUNT(*) FROM documents")
                total_documents = cur.fetchone()[0]

                cur.execute("SELECT COUNT(*) FROM chunks")
                total_chunks = cur.fetchone()[0]

                cur.execute("SELECT MAX(ingested_at) FROM documents")
                row = cur.fetchone()
                if row and row[0]:
                    last_ingestion = row[0].isoformat()
        finally:
            conn.rollback()
            put_connection(conn)
    except Exception as exc:
        db_status = f"unhealthy: {type(exc).__name__}"
        logger.warning("Health check: DB unhealthy — %s", type(exc).__name__)

    # --- Ollama ---
    ollama_status = "healthy"
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(OLLAMA_URL)
            resp.raise_for_status()
    except Exception as exc:
        ollama_status = f"unhealthy: {type(exc).__name__}"
        logger.warning("Health check: Ollama unhealthy — %s", type(exc).__name__)

    overall = "healthy" if db_status == "healthy" and ollama_status == "healthy" else "degraded"

    return {
        "status": overall,
        "uptime_seconds": uptime_seconds,
        "database": {
            "status": db_status,
            "total_documents": total_documents,
            "total_chunks": total_chunks,
            "last_ingestion": last_ingestion,
        },
        "ollama": {
            "status": ollama_status,
        },
    }
