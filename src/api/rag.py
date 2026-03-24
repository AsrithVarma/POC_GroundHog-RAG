import logging
import threading
import uuid
from collections.abc import Generator

from src.api.db import get_connection, put_connection
from src.api.llm_client import generate
from src.api.prompt_builder import build_prompt
from src.api.retriever import retrieve

logger = logging.getLogger(__name__)


def _write_audit_log(
    user_id: str,
    query_text: str,
    chunk_ids: list[str],
    response_text: str,
) -> None:
    """Insert an audit log entry. Runs in a background thread."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO audit_log (id, user_id, query_text, retrieved_chunk_ids, response_text)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (
                    str(uuid.uuid4()),
                    user_id,
                    query_text,
                    chunk_ids,
                    response_text,
                ),
            )
            conn.commit()
        logger.info("Audit log written for user %s", user_id)
    except Exception:
        conn.rollback()
        logger.error("Failed to write audit log for user %s", user_id, exc_info=True)
    finally:
        put_connection(conn)


def answer(
    question: str,
    user_id: str,
    access_group: str | None = None,
    top_k: int = 5,
) -> Generator[str, None, None]:
    """Full RAG pipeline: retrieve, build prompt, generate, audit.

    Yields tokens from the LLM as they stream in. After the final token,
    yields a JSON-formatted source citations block. Writes an audit log
    entry in a background thread once generation completes.

    Args:
        question: the user's question.
        user_id: UUID of the authenticated user (for audit logging).
        access_group: RBAC filter — only retrieve chunks from documents
                      in this group. None retrieves from all.
        top_k: number of chunks to retrieve.

    Yields:
        Token strings from the LLM, followed by a citations block.
    """
    # Step 1: Retrieve
    chunks = retrieve(question, top_k=top_k, access_group=access_group)
    chunk_ids = [c["chunk_id"] for c in chunks]

    logger.info(
        "RAG pipeline — user=%s, chunks_retrieved=%d, access_group=%s",
        user_id,
        len(chunks),
        access_group,
    )

    if not chunks:
        no_context = (
            "I don't have enough information to answer that question "
            "based on the available documents."
        )
        # Audit even when no context is found
        thread = threading.Thread(
            target=_write_audit_log,
            args=(user_id, question, [], no_context),
            daemon=True,
        )
        thread.start()
        yield no_context
        return

    # Step 2: Build prompt
    prompt = build_prompt(question, chunks)

    # Step 3: Generate (streaming)
    response_parts: list[str] = []

    for token in generate(prompt):
        response_parts.append(token)
        yield token

    # Step 4: Source citations
    sources = []
    seen = set()
    for c in chunks:
        key = (c["source_file"], c["page_number"])
        if key not in seen:
            seen.add(key)
            sources.append(
                {
                    "file": c["source_file"],
                    "page": c["page_number"],
                    "similarity": round(c["similarity_score"], 4),
                }
            )

    citations_block = "\n\n---\nSources:\n"
    for s in sources:
        citations_block += f"- {s['file']}, Page {s['page']} (similarity: {s['similarity']})\n"

    yield citations_block

    # Step 5: Audit log (background)
    full_response = "".join(response_parts)
    # Truncate response for audit to avoid storing huge LLM outputs
    audit_response = full_response[:1000] if len(full_response) > 1000 else full_response

    thread = threading.Thread(
        target=_write_audit_log,
        args=(user_id, question, chunk_ids, audit_response),
        daemon=True,
    )
    thread.start()
