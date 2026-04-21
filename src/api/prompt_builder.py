import logging

logger = logging.getLogger(__name__)

SYSTEM_MESSAGE = (
    "Answer using ONLY the context below. Cite sources as (Source: filename, Page N). "
    "Use bullet points for lists. Bold key terms. "
    "If the context is unrelated, say so. Be concise."
)

CHARS_PER_TOKEN_ESTIMATE = 4


def build_prompt(
    question: str,
    chunks: list[dict],
    max_context_tokens: int = 3072,
) -> str:
    """Assemble a prompt from retrieved chunks and a user question.

    Chunks are expected to be sorted by similarity (highest first).
    Lower-similarity chunks are truncated first when the context
    exceeds max_context_tokens.

    Args:
        question: the user's question.
        chunks: list of dicts with keys: chunk_text, source_file,
                page_number, similarity_score.
        max_context_tokens: approximate token budget for the context
                           section. Chunks are dropped from the end
                           (lowest similarity) to fit.

    Returns:
        The fully assembled prompt string.
    """
    max_context_chars = max_context_tokens * CHARS_PER_TOKEN_ESTIMATE

    # Build context blocks, dropping lowest-similarity chunks to fit budget
    context_blocks: list[str] = []
    total_chars = 0

    for chunk in chunks:
        block = (
            f"[Source: {chunk['source_file']}, Page {chunk['page_number']}]\n"
            f"{chunk['chunk_text']}"
        )

        if total_chars + len(block) > max_context_chars:
            logger.info(
                "Context budget reached — kept %d/%d chunks (limit ~%d tokens)",
                len(context_blocks),
                len(chunks),
                max_context_tokens,
            )
            break

        context_blocks.append(block)
        total_chars += len(block)

    if not context_blocks:
        context_section = "(No relevant context found.)"
    else:
        context_section = "\n\n---\n\n".join(context_blocks)

    # Wrap question in delimiters to reduce prompt injection risk
    prompt = (
        f"### System\n{SYSTEM_MESSAGE}\n\n"
        f"### Context\n{context_section}\n\n"
        f'### User Question (answer ONLY from the context above)\n"""\n{question}\n"""'
    )

    logger.info(
        "Built prompt — %d chunks, ~%d context chars, question length %d",
        len(context_blocks),
        total_chars,
        len(question),
    )

    return prompt
