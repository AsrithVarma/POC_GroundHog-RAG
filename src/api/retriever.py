import logging
import os
import time

from src.api.db import get_connection, put_connection
from src.api.embedder import embed_query

logger = logging.getLogger(__name__)

MIN_SIMILARITY = float(os.environ.get("MIN_SIMILARITY", "0.3"))
HNSW_EF_SEARCH = int(os.environ.get("HNSW_EF_SEARCH", "100"))


def retrieve(
    query: str,
    top_k: int = 10,
    access_group: str | None = None,
) -> list[dict]:
    """Embed a query and return the top-k most similar chunks.

    Filters out chunks below MIN_SIMILARITY threshold.
    Sets hnsw.ef_search for better recall on the HNSW index.
    Results are sorted by similarity (highest first), then grouped
    by document/page for coherence.
    """
    t0 = time.perf_counter()
    query_embedding = embed_query(query)
    embed_ms = (time.perf_counter() - t0) * 1000

    embedding_literal = str(query_embedding)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Tune HNSW search: higher ef_search = better recall, slightly slower
            cur.execute(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}")

            t1 = time.perf_counter()
            cur.execute(
                """
                SELECT
                    c.id,
                    c.chunk_text,
                    c.page_number,
                    c.document_id,
                    d.filename,
                    1 - (c.embedding <=> %s::vector) AS similarity,
                    c.chunk_index
                FROM chunks c
                JOIN documents d ON d.id = c.document_id
                WHERE (d.access_group = %s OR %s IS NULL)
                  AND 1 - (c.embedding <=> %s::vector) > %s
                ORDER BY c.embedding <=> %s::vector
                LIMIT %s
                """,
                (
                    embedding_literal,
                    access_group, access_group,
                    embedding_literal, MIN_SIMILARITY,
                    embedding_literal,
                    top_k,
                ),
            )
            rows = cur.fetchall()
            search_ms = (time.perf_counter() - t1) * 1000
    finally:
        conn.rollback()
        put_connection(conn)

    results = [
        {
            "chunk_id": str(row[0]),
            "chunk_text": row[1],
            "page_number": row[2],
            "document_id": str(row[3]),
            "source_file": row[4],
            "similarity_score": float(row[5]),
            "chunk_index": row[6],
        }
        for row in rows
    ]

    results.sort(key=lambda c: (c["source_file"], c["page_number"], c["chunk_index"]))

    logger.info(
        "Retrieved %d chunks (top_k=%d, group=%s, min_sim=%.2f, "
        "ef_search=%d, embed=%.0fms, search=%.0fms)",
        len(results),
        top_k,
        access_group,
        MIN_SIMILARITY,
        HNSW_EF_SEARCH,
        embed_ms,
        search_ms,
    )

    return results
