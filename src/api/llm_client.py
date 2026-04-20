import json
import logging
import time
from collections.abc import Generator

import httpx

logger = logging.getLogger(__name__)

OLLAMA_GENERATE_URL = "http://ollama:11434/api/generate"
DEFAULT_MODEL = "llama3.2:3b"
REQUEST_TIMEOUT = 300.0
TEMPERATURE = 0.1

_client = httpx.Client(timeout=REQUEST_TIMEOUT)


def generate(
    prompt: str,
    model: str = DEFAULT_MODEL,
    stream: bool = True,
) -> Generator[str, None, None]:
    """Call Ollama generate API, yielding tokens as they arrive.

    Args:
        prompt: the assembled prompt string.
        model: Ollama model name.
        stream: if True, stream tokens via SSE. If False, return the
                full response as a single yield.

    Yields:
        Individual token strings (streaming) or the full response text
        (non-streaming).
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": stream,
        "options": {
            "temperature": TEMPERATURE,
        },
    }

    start = time.monotonic()
    token_count = 0

    if stream:
        try:
            with _client.stream("POST", OLLAMA_GENERATE_URL, json=payload) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    token = chunk.get("response", "")
                    if token:
                        token_count += 1
                        yield token

                    if chunk.get("done", False):
                        break

            elapsed = time.monotonic() - start
            logger.info(
                "Streaming complete — model=%s, tokens=%d, latency=%.1fs",
                model,
                token_count,
                elapsed,
            )
            return

        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            logger.warning(
                "Streaming failed (%s), falling back to non-streaming",
                type(exc).__name__,
            )
            # Fall through to non-streaming

    # Non-streaming mode (also used as fallback)
    payload["stream"] = False

    try:
        response = _client.post(OLLAMA_GENERATE_URL, json=payload)
        response.raise_for_status()
        data = response.json()

        elapsed = time.monotonic() - start
        text = data.get("response", "")
        token_count = data.get("eval_count", len(text.split()))

        logger.info(
            "Non-streaming complete — model=%s, tokens=%d, latency=%.1fs",
            model,
            token_count,
            elapsed,
        )

        yield text

    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        elapsed = time.monotonic() - start
        logger.error(
            "LLM request failed — model=%s, latency=%.1fs, error=%s",
            model,
            elapsed,
            type(exc).__name__,
        )
        raise
