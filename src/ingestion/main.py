import argparse
import hashlib
import logging
import sys
from pathlib import Path

from tqdm import tqdm

from src.ingestion.chunker import chunk_pages, dry_run_report
from src.ingestion.embedder import embed_texts
from src.ingestion.extractor import extract_pdf
from src.ingestion import loader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

PDF_DIR = Path("/data/pdfs")
DEFAULT_ACCESS_GROUP = "default"


def compute_file_hash(file_path: Path) -> str:
    """SHA-256 hash of the file contents."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            h.update(block)
    return h.hexdigest()


def check_already_ingested(file_hash: str) -> bool:
    """Check if a file hash already exists in the database."""
    conn = loader.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM documents WHERE file_hash = %s", (file_hash,))
            return cur.fetchone() is not None
    finally:
        conn.rollback()
        loader.put_connection(conn)


def process_file(
    pdf_path: Path,
    dry_run: bool = False,
    reindex: bool = False,
    access_group: str = DEFAULT_ACCESS_GROUP,
) -> dict:
    """Process a single PDF through the full pipeline.

    Returns a stats dict with keys: status, filename, chunks, pages.
    """
    filename = pdf_path.name
    file_hash = compute_file_hash(pdf_path)

    if not dry_run and not reindex:
        if check_already_ingested(file_hash):
            logger.info("Skipping (duplicate): %s", filename)
            return {"status": "skipped", "filename": filename, "chunks": 0, "pages": 0}

    # Extract
    logger.info("Extracting: %s", filename)
    pages = extract_pdf(pdf_path)

    # Chunk
    chunks = chunk_pages(pages, source_file=filename)

    if dry_run:
        dry_run_report(chunks)
        return {
            "status": "dry_run",
            "filename": filename,
            "chunks": len(chunks),
            "pages": len(pages),
        }

    # Embed
    logger.info("Embedding %d chunks for %s", len(chunks), filename)
    texts = [c.text for c in chunks]
    embeddings = embed_texts(texts)

    # Upsert document
    if reindex:
        # Delete existing document and chunks so we can reinsert
        conn = loader.get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM documents WHERE file_hash = %s", (file_hash,))
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            loader.put_connection(conn)

    doc_id = loader.upsert_document(filename, file_hash, len(pages), access_group)

    if doc_id is None:
        logger.info("Skipping (duplicate after upsert check): %s", filename)
        return {"status": "skipped", "filename": filename, "chunks": 0, "pages": len(pages)}

    # Insert chunks
    chunks_with_embeddings = [
        {
            "text": c.text,
            "chunk_index": c.chunk_index,
            "page_number": c.page_number,
            "embedding": emb,
        }
        for c, emb in zip(chunks, embeddings)
    ]

    inserted = loader.insert_chunks(doc_id, chunks_with_embeddings)

    return {
        "status": "ingested",
        "filename": filename,
        "chunks": inserted,
        "pages": len(pages),
    }


def main():
    parser = argparse.ArgumentParser(description="PDF ingestion pipeline")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract and chunk but do not write to the database",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="Reprocess all files, replacing existing entries",
    )
    parser.add_argument(
        "--access-group",
        default=DEFAULT_ACCESS_GROUP,
        help="Access group to assign to ingested documents",
    )
    args = parser.parse_args()

    pdf_files = sorted(PDF_DIR.glob("**/*.pdf"))

    if not pdf_files:
        logger.warning("No PDF files found in %s", PDF_DIR)
        sys.exit(0)

    logger.info("Found %d PDF files in %s", len(pdf_files), PDF_DIR)

    stats = {"ingested": 0, "skipped": 0, "failed": 0, "dry_run": 0, "total_chunks": 0}

    for pdf_path in tqdm(pdf_files, desc="Processing PDFs", unit="file"):
        try:
            result = process_file(
                pdf_path,
                dry_run=args.dry_run,
                reindex=args.reindex,
                access_group=args.access_group,
            )
            stats[result["status"]] = stats.get(result["status"], 0) + 1
            stats["total_chunks"] += result["chunks"]
        except Exception:
            logger.error("Failed to process: %s", pdf_path.name, exc_info=True)
            stats["failed"] += 1

    logger.info("=" * 50)
    logger.info("Pipeline complete")
    logger.info("  Files found:    %d", len(pdf_files))
    logger.info("  Ingested:       %d", stats["ingested"])
    logger.info("  Skipped (dup):  %d", stats["skipped"])
    logger.info("  Failed:         %d", stats["failed"])
    logger.info("  Dry-run only:   %d", stats["dry_run"])
    logger.info("  Total chunks:   %d", stats["total_chunks"])


if __name__ == "__main__":
    main()
