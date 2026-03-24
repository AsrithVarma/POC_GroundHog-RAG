FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    pymupdf \
    pdfplumber \
    langchain-text-splitters \
    psycopg2-binary \
    python-dotenv \
    httpx \
    tqdm

COPY src/__init__.py src/__init__.py
COPY src/ingestion/ src/ingestion/

ENTRYPOINT ["python", "-m", "src.ingestion.main"]
