import logging
import os
import uuid

import psycopg2
import psycopg2.pool
from psycopg2.extras import execute_values

logger = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None or _pool.closed:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=4,
            host=os.environ["POSTGRES_HOST"],
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
        )
        logger.info("Database connection pool created")
    return _pool


def get_connection():
    return _get_pool().getconn()


def put_connection(conn):
    _get_pool().putconn(conn)


def upsert_document(
    filename: str,
    file_hash: str,
    page_count: int,
    access_group: str,
) -> str | None:
    """Insert a document if its file_hash doesn't already exist.

    Returns:
        The document UUID if inserted, or None if the hash already exists (skipped).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM documents WHERE file_hash = %s",
                (file_hash,),
            )
            existing = cur.fetchone()
            if existing:
                logger.info("Skipping duplicate document: %s (hash=%s…)", filename, file_hash[:12])
                conn.rollback()
                return None

            doc_id = str(uuid.uuid4())
            cur.execute(
                """
                INSERT INTO documents (id, filename, file_hash, page_count, access_group)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (doc_id, filename, file_hash, page_count, access_group),
            )
            conn.commit()
            logger.info("Inserted document: %s (id=%s)", filename, doc_id)
            return doc_id
    except Exception:
        conn.rollback()
        logger.error("Failed to upsert document: %s", filename)
        raise
    finally:
        put_connection(conn)


def insert_chunks(document_id: str, chunks_with_embeddings: list[dict]) -> int:
    """Batch-insert chunks with embeddings for a document.

    Each dict in chunks_with_embeddings must have:
        text, chunk_index, page_number, embedding (list[float])

    The entire batch is inserted in a single transaction — if any chunk
    fails, all chunks for this document are rolled back.

    Returns:
        Number of chunks inserted.
    """
    if not chunks_with_embeddings:
        return 0

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            values = [
                (
                    str(uuid.uuid4()),
                    document_id,
                    chunk["text"],
                    chunk["chunk_index"],
                    chunk["page_number"],
                    "[" + ",".join(str(v) for v in chunk["embedding"]) + "]",
                )
                for chunk in chunks_with_embeddings
            ]

            execute_values(
                cur,
                """
                INSERT INTO chunks (id, document_id, chunk_text, chunk_index, page_number, embedding)
                VALUES %s
                """,
                values,
                template="(%s, %s, %s, %s, %s, %s::vector)",
            )

            conn.commit()
            logger.info(
                "Inserted %d chunks for document %s",
                len(values),
                document_id,
            )
            return len(values)
    except Exception:
        conn.rollback()
        logger.error("Chunk insert failed for document %s — rolled back", document_id)
        raise
    finally:
        put_connection(conn)
