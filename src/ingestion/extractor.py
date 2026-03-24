import logging
from pathlib import Path

import fitz
import pdfplumber

logger = logging.getLogger(__name__)

MIN_TEXT_LENGTH = 50


def extract_pdf(file_path: str | Path) -> list[dict]:
    """Extract text and tables from a PDF, returning one dict per page.

    Each dict contains:
        page_number: 1-based page index
        text: extracted text content
        tables: list of tables, each table a list of rows (list of str)
    """
    file_path = Path(file_path)
    pages: list[dict] = []

    try:
        fitz_doc = fitz.open(file_path)
    except Exception:
        logger.error("Failed to open PDF with PyMuPDF: %s", file_path.name)
        raise

    try:
        plumber_doc = pdfplumber.open(file_path)
    except Exception:
        logger.error("Failed to open PDF with pdfplumber: %s", file_path.name)
        fitz_doc.close()
        raise

    total_chars = 0
    fallback_count = 0

    try:
        for page_idx in range(len(fitz_doc)):
            page_number = page_idx + 1

            try:
                text = fitz_doc[page_idx].get_text()
            except Exception:
                logger.warning(
                    "PyMuPDF failed on page %d of %s", page_number, file_path.name
                )
                text = ""

            if len(text.strip()) < MIN_TEXT_LENGTH:
                try:
                    plumber_page = plumber_doc.pages[page_idx]
                    plumber_text = plumber_page.extract_text() or ""
                    if len(plumber_text.strip()) > len(text.strip()):
                        text = plumber_text
                        fallback_count += 1
                except Exception:
                    logger.warning(
                        "pdfplumber fallback failed on page %d of %s",
                        page_number,
                        file_path.name,
                    )

            tables: list[list] = []
            try:
                plumber_page = plumber_doc.pages[page_idx]
                raw_tables = plumber_page.extract_tables() or []
                for table in raw_tables:
                    cleaned = [
                        [cell if cell is not None else "" for cell in row]
                        for row in table
                    ]
                    tables.append(cleaned)
            except Exception:
                logger.warning(
                    "Table extraction failed on page %d of %s",
                    page_number,
                    file_path.name,
                )

            total_chars += len(text)
            pages.append(
                {"page_number": page_number, "text": text, "tables": tables}
            )
    finally:
        fitz_doc.close()
        plumber_doc.close()

    logger.info(
        "Extracted %d pages from %s — %d total chars, %d pdfplumber fallbacks",
        len(pages),
        file_path.name,
        total_chars,
        fallback_count,
    )

    return pages
