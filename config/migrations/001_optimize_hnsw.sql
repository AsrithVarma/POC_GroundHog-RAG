-- Migration 001: Optimize HNSW index and add supporting B-tree indexes
-- Run this against an existing database to apply the optimizations.
--
-- Usage (from project root):
--   docker compose exec postgres psql -U raguser -d ragdb -f /migrations/001_optimize_hnsw.sql
--
-- For fresh deployments this is already included in init.sql.

BEGIN;

-- Recreate HNSW index with higher ef_construction for better graph quality
DROP INDEX IF EXISTS idx_chunks_embedding;
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- B-tree index on chunks.document_id to speed up the JOIN
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON chunks (document_id);

-- B-tree index on documents.access_group to speed up RBAC filtering
CREATE INDEX IF NOT EXISTS idx_documents_access_group ON documents (access_group);

COMMIT;
