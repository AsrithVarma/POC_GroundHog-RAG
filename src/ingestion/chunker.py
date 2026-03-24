import hashlib
import logging
from dataclasses import dataclass, field

from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 1000
DEFAULT_CHUNK_OVERLAP = 150


@dataclass
class Chunk:
    text: str
    source_file: str
    page_number: int
    chunk_index: int
    char_start: int
    char_end: int
    sha256: str = field(init=False)

    def __post_init__(self):
        self.sha256 = hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def chunk_pages(
    pages: list[dict],
    source_file: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[Chunk]:
    """Split extracted pages into overlapping chunks with metadata.

    Args:
        pages: list of dicts from extractor.extract_pdf, each with
               'page_number' and 'text' keys.
        source_file: filename used in chunk metadata.
        chunk_size: max characters per chunk.
        chunk_overlap: overlap between consecutive chunks.

    Returns:
        list of Chunk objects with metadata and SHA-256 hash.
    """
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=len,
    )

    chunks: list[Chunk] = []
    global_index = 0

    for page in pages:
        page_text = page["text"]
        page_number = page["page_number"]

        if not page_text or not page_text.strip():
            continue

        splits = splitter.split_text(page_text)

        search_start = 0
        for split_text in splits:
            char_start = page_text.find(split_text, search_start)
            if char_start == -1:
                char_start = search_start
            char_end = char_start + len(split_text)
            search_start = max(char_start + 1, search_start)

            chunks.append(
                Chunk(
                    text=split_text,
                    source_file=source_file,
                    page_number=page_number,
                    chunk_index=global_index,
                    char_start=char_start,
                    char_end=char_end,
                )
            )
            global_index += 1

    logger.info(
        "Chunked %s — %d pages → %d chunks (size=%d, overlap=%d)",
        source_file,
        len(pages),
        len(chunks),
        chunk_size,
        chunk_overlap,
    )

    return chunks


def dry_run_report(chunks: list[Chunk]) -> dict:
    """Print and return chunk statistics without writing to the database."""
    if not chunks:
        report = {"total_chunks": 0, "avg_size": 0.0, "min_size": 0, "max_size": 0}
        logger.info("Dry run: no chunks produced")
        return report

    sizes = [len(c.text) for c in chunks]
    unique_hashes = len({c.sha256 for c in chunks})

    report = {
        "total_chunks": len(chunks),
        "unique_chunks": unique_hashes,
        "duplicates": len(chunks) - unique_hashes,
        "avg_size": sum(sizes) / len(sizes),
        "min_size": min(sizes),
        "max_size": max(sizes),
    }

    logger.info(
        "Dry run for %s — %d chunks (%d unique, %d dupes), "
        "avg %.0f chars, min %d, max %d",
        chunks[0].source_file,
        report["total_chunks"],
        report["unique_chunks"],
        report["duplicates"],
        report["avg_size"],
        report["min_size"],
        report["max_size"],
    )

    return report
