import logging

from src.api.db import get_connection, put_connection
from src.api.embedder import embed_query

logger = logging.getLogger(__name__)

MIN_SIMILARITY = 0.3


def retrieve(
    query: str,
    top_k: int = 10,
    access_group: str | None = None,
) -> list[dict]:
    """Embed a query and return the top-k most similar chunks.

    Filters out chunks below MIN_SIMILARITY threshold.
    Results are sorted by similarity (highest first), then grouped
    by document/page for coherence.
    """
    query_embedding = embed_query(query)
    # pgvector expects format: [1.2,3.4,...] — Python str() on a list produces this
    embedding_literal = str(query_embedding)

    conn = get_connection()
    try:
        with conn.cursor() as cur:
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

    # Re-sort: group by document then page for coherent context
    results.sort(key=lambda c: (c["source_file"], c["page_number"], c["chunk_index"]))

    logger.info(
        "Retrieved %d chunks for query (top_k=%d, access_group=%s, min_sim=%.2f)",
        len(results),
        top_k,
        access_group,
        MIN_SIMILARITY,
    )

    return results
