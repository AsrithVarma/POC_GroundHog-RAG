import logging
import time

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434/api/embeddings"
MODEL_NAME = "nomic-embed-text"
EMBEDDING_DIM = 768

MAX_RETRIES = 5
BACKOFF_BASE = 2.0
REQUEST_TIMEOUT = 120.0

_client = httpx.Client(timeout=REQUEST_TIMEOUT)


def embed_query(text: str) -> list[float]:
    """Embed a single query string via Ollama, returning a 768-dim vector."""
    for attempt in range(MAX_RETRIES):
        try:
            response = _client.post(
                OLLAMA_URL,
                json={"model": MODEL_NAME, "prompt": text},
            )
            response.raise_for_status()
            embedding = response.json()["embedding"]

            if len(embedding) != EMBEDDING_DIM:
                raise ValueError(
                    f"Expected {EMBEDDING_DIM}-dim vector, got {len(embedding)}-dim"
                )

            return embedding
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, ValueError) as exc:
            if attempt == MAX_RETRIES - 1:
                logger.error(
                    "Query embedding failed after %d retries: %s",
                    MAX_RETRIES,
                    type(exc).__name__,
                )
                raise
            wait = BACKOFF_BASE ** attempt
            logger.warning(
                "Embed attempt %d/%d failed (%s), retrying in %.1fs",
                attempt + 1,
                MAX_RETRIES,
                type(exc).__name__,
                wait,
            )
            time.sleep(wait)
    return []  # unreachable, satisfies type checker
