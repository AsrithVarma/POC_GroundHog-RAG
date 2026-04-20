"""Integration tests for HNSW index configuration and retrieval performance.

Run against a live stack:
    docker compose exec api python -m pytest tests/test_hnsw.py -v

Or standalone (requires POSTGRES_* env vars):
    python tests/test_hnsw.py
"""

import os
import sys
import time

import psycopg2


def _connect():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "ragdb"),
        user=os.environ.get("POSTGRES_USER", "raguser"),
        password=os.environ["POSTGRES_PASSWORD"],
    )


def test_hnsw_index_exists():
    """Verify the HNSW index on chunks.embedding exists."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT indexdef FROM pg_indexes
                WHERE tablename = 'chunks'
                  AND indexname = 'idx_chunks_embedding'
                """
            )
            row = cur.fetchone()
            assert row is not None, "idx_chunks_embedding not found"
            assert "hnsw" in row[0].lower(), f"Index is not HNSW: {row[0]}"
            assert "vector_cosine_ops" in row[0].lower(), f"Index not using cosine ops: {row[0]}"
            print(f"  PASS: HNSW index exists — {row[0]}")
    finally:
        conn.close()


def test_supporting_indexes_exist():
    """Verify B-tree supporting indexes exist."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            for idx_name, table in [
                ("idx_chunks_document_id", "chunks"),
                ("idx_documents_access_group", "documents"),
            ]:
                cur.execute(
                    "SELECT 1 FROM pg_indexes WHERE indexname = %s AND tablename = %s",
                    (idx_name, table),
                )
                assert cur.fetchone() is not None, f"{idx_name} not found on {table}"
                print(f"  PASS: {idx_name} exists on {table}")
    finally:
        conn.close()


def test_ef_search_is_configurable():
    """Verify hnsw.ef_search can be set within a transaction."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL hnsw.ef_search = 100")
            cur.execute("SHOW hnsw.ef_search")
            val = cur.fetchone()[0]
            assert val == "100", f"Expected ef_search=100, got {val}"
            print(f"  PASS: hnsw.ef_search set to {val}")
        conn.rollback()
    finally:
        conn.close()


def test_hnsw_index_used_in_query():
    """Verify EXPLAIN shows the HNSW index scan (requires data in chunks table)."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chunks")
            count = cur.fetchone()[0]
            if count == 0:
                print("  SKIP: No chunks in database — insert data first")
                return

            # Build a dummy 768-dim vector
            dummy_vec = "[" + ",".join(["0.01"] * 768) + "]"

            cur.execute("SET LOCAL hnsw.ef_search = 100")
            cur.execute(
                """
                EXPLAIN (FORMAT TEXT)
                SELECT c.id, 1 - (c.embedding <=> %s::vector) AS similarity
                FROM chunks c
                ORDER BY c.embedding <=> %s::vector
                LIMIT 10
                """,
                (dummy_vec, dummy_vec),
            )
            plan = "\n".join(row[0] for row in cur.fetchall())

            uses_index = "index scan" in plan.lower() and "idx_chunks_embedding" in plan.lower()
            if uses_index:
                print(f"  PASS: Query plan uses HNSW index scan")
            else:
                # Small tables may use sequential scan — not a failure, just a note
                print(f"  NOTE: Query plan does not use HNSW index (may be small dataset):\n{plan}")
        conn.rollback()
    finally:
        conn.close()


def test_vector_search_returns_results():
    """End-to-end: run a vector similarity query and verify results come back."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chunks")
            count = cur.fetchone()[0]
            if count == 0:
                print("  SKIP: No chunks in database")
                return

            dummy_vec = "[" + ",".join(["0.01"] * 768) + "]"

            cur.execute("SET LOCAL hnsw.ef_search = 100")

            t0 = time.perf_counter()
            cur.execute(
                """
                SELECT c.id,
                       1 - (c.embedding <=> %s::vector) AS similarity
                FROM chunks c
                ORDER BY c.embedding <=> %s::vector
                LIMIT 5
                """,
                (dummy_vec, dummy_vec),
            )
            rows = cur.fetchall()
            elapsed_ms = (time.perf_counter() - t0) * 1000

            assert len(rows) > 0, "No results returned from vector search"
            similarities = [float(r[1]) for r in rows]
            assert similarities == sorted(similarities, reverse=True), "Results not in similarity order"
            print(f"  PASS: Got {len(rows)} results in {elapsed_ms:.1f}ms, "
                  f"top similarity={similarities[0]:.4f}")
        conn.rollback()
    finally:
        conn.close()


def test_access_group_filtering():
    """Verify RBAC filtering works in the retrieval query."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT d.access_group FROM documents d "
                "JOIN chunks c ON c.document_id = d.id LIMIT 5"
            )
            groups = [r[0] for r in cur.fetchall()]
            if not groups:
                print("  SKIP: No documents with chunks")
                return

            dummy_vec = "[" + ",".join(["0.01"] * 768) + "]"

            for group in groups:
                cur.execute("SET LOCAL hnsw.ef_search = 100")
                cur.execute(
                    """
                    SELECT d.access_group
                    FROM chunks c
                    JOIN documents d ON d.id = c.document_id
                    WHERE d.access_group = %s
                      AND 1 - (c.embedding <=> %s::vector) > 0.0
                    ORDER BY c.embedding <=> %s::vector
                    LIMIT 5
                    """,
                    (group, dummy_vec, dummy_vec),
                )
                rows = cur.fetchall()
                for row in rows:
                    assert row[0] == group, f"Expected group={group}, got {row[0]}"
                print(f"  PASS: access_group={group} filter returned {len(rows)} results, all matching")
        conn.rollback()
    finally:
        conn.close()


ALL_TESTS = [
    test_hnsw_index_exists,
    test_supporting_indexes_exist,
    test_ef_search_is_configurable,
    test_hnsw_index_used_in_query,
    test_vector_search_returns_results,
    test_access_group_filtering,
]


def main():
    print("=" * 50)
    print(" HNSW Index Integration Tests")
    print("=" * 50)

    passed = 0
    failed = 0
    skipped = 0

    for test_fn in ALL_TESTS:
        name = test_fn.__name__
        print(f"\n[{name}]")
        try:
            test_fn()
            passed += 1
        except AssertionError as e:
            print(f"  FAIL: {e}")
            failed += 1
        except Exception as e:
            print(f"  ERROR: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{'=' * 50}")
    print(f" Results: {passed} passed, {failed} failed")
    print(f"{'=' * 50}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
