import logging
import os
import time

import httpx

logger = logging.getLogger(__name__)

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://ollama:11434")
OLLAMA_URL = f"{OLLAMA_HOST}/api/embeddings"
MODEL_NAME = "nomic-embed-text"
EMBEDDING_DIM = 768

MAX_RETRIES = 5
BACKOFF_BASE = 2.0
REQUEST_TIMEOUT = 120.0


def _embed_single(client: httpx.Client, text: str) -> list[float]:
    """Call Ollama embeddings API for a single text with exponential backoff."""
    for attempt in range(MAX_RETRIES):
        try:
            response = client.post(
                OLLAMA_URL,
                json={"model": MODEL_NAME, "prompt": text},
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            return response.json()["embedding"]
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError) as exc:
            if attempt == MAX_RETRIES - 1:
                logger.error(
                    "Embedding failed after %d retries: %s", MAX_RETRIES, type(exc).__name__
                )
                raise
            wait = BACKOFF_BASE ** attempt
            logger.warning(
                "Embedding attempt %d/%d failed (%s), retrying in %.1fs",
                attempt + 1,
                MAX_RETRIES,
                type(exc).__name__,
                wait,
            )
            time.sleep(wait)
    return []  # unreachable, satisfies type checker


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a list of strings via Ollama nomic-embed-text, returning 768-dim vectors."""
    if not texts:
        return []

    embeddings: list[list[float]] = []

    with httpx.Client() as client:
        for i, text in enumerate(texts):
            vector = _embed_single(client, text)
            embeddings.append(vector)

            if (i + 1) % 50 == 0:
                logger.info("Embedded %d/%d texts", i + 1, len(texts))

    logger.info("Embedded %d texts via %s", len(texts), MODEL_NAME)
    return embeddings


# Self-test: verify Ollama connectivity and output dimension
def _self_test():
    try:
        result = embed_texts(["self-test"])
        assert len(result) == 1, f"Expected 1 embedding, got {len(result)}"
        assert len(result[0]) == EMBEDDING_DIM, (
            f"Expected {EMBEDDING_DIM}-dim vector, got {len(result[0])}-dim"
        )
        logger.info("Embedder self-test passed — model=%s, dim=%d", MODEL_NAME, EMBEDDING_DIM)
    except Exception:
        logger.warning(
            "Embedder self-test failed — Ollama may not be ready yet. "
            "The pipeline will retry on first real embed call."
        )


_self_test()
