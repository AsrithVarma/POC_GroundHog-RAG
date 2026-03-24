-- Enable pgvector extension for vector similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Users table for authentication and RBAC
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    access_group TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Documents table with file_hash for deduplication
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    file_hash TEXT UNIQUE NOT NULL,
    page_count INT,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    access_group TEXT NOT NULL
);

-- Chunks table storing text segments and their embeddings
-- vector(768) sized for nomic-embed-text via Ollama
CREATE TABLE chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_text TEXT NOT NULL,
    chunk_index INT NOT NULL,
    page_number INT,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index on chunk embeddings using cosine distance
--
-- HNSW tuning parameters:
--   m              — max connections per node in the graph (default 16).
--                    Higher values improve recall but increase memory usage
--                    and index build time. 16 is a good baseline; increase
--                    to 32–64 for higher recall on large datasets.
--   ef_construction — search width during index build (default 64).
--                    Higher values produce a better-quality graph at the cost
--                    of slower index creation. 128–200 is typical for
--                    production workloads where recall matters.
--
-- At query time, set hnsw.ef_search (default 40) to control the recall/speed
-- tradeoff. Higher values scan more candidates and improve recall but slow
-- down each query. Start with 100 and tune from there.
CREATE INDEX idx_chunks_embedding ON chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 128);

-- Audit log for tracking all RAG queries and responses
CREATE TABLE audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID REFERENCES users(id),
    query_text TEXT NOT NULL,
    retrieved_chunk_ids UUID[] NOT NULL,
    response_text TEXT,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT now()
);
