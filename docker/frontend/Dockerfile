FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir \
    streamlit \
    httpx \
    python-dotenv

COPY src/__init__.py src/__init__.py
COPY src/frontend/ src/frontend/

EXPOSE 3000

ENTRYPOINT ["streamlit", "run", "src/frontend/app.py", "--server.port=3000", "--server.address=0.0.0.0", "--server.headless=true"]
