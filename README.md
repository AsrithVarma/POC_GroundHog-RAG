# GroundHog RAG — Private Document Q&A System

A fully self-hosted RAG (Retrieval-Augmented Generation) system. Ask questions about your PDF documents and get cited answers — nothing leaves your machine.

## Prerequisites

| Requirement | macOS | Windows |
|---|---|---|
| **Docker Desktop** | [Download for Mac](https://www.docker.com/products/docker-desktop/) | [Download for Windows](https://www.docker.com/products/docker-desktop/) |
| **Ollama** | `brew install ollama` | [Download for Windows](https://ollama.com/download/windows) |
| **RAM** | 8 GB+ (16 GB recommended) | 8 GB+ |
| **Disk space** | 10 GB for images and models | 10 GB for images and models |
| **Git** | Pre-installed (or `xcode-select --install`) | [Download Git](https://git-scm.com/download/win) |

## Setup — macOS (Apple Silicon M1/M2/M3/M4)

Apple Silicon Macs get **GPU-accelerated inference** because Ollama runs natively on macOS with full Metal GPU access. Responses typically arrive in **5-10 seconds**.

### Step 1: Install prerequisites

```bash
# Install Homebrew if you don't have it
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Ollama
brew install ollama
```

Open **Docker Desktop** and go to **Settings > Resources** — set memory to **8 GB or higher**.

### Step 2: Start Ollama and pull models

```bash
# Start the Ollama server (runs in the background)
ollama serve &

# Pull the embedding model (~274 MB)
ollama pull nomic-embed-text

# Pull the LLM (~2 GB)
ollama pull llama3.2:3b
```

### Step 3: Clone and run the setup script

```bash
git clone https://github.com/AsrithVarma/POC_GroundHog-RAG.git
cd POC_GroundHog-RAG

# Create a folder for your PDFs
mkdir -p ~/Documents/rag-pdfs

# Run the setup script (pass your PDF folder path)
bash scripts/setup.sh ~/Documents/rag-pdfs
```

The script will:
1. Generate a `.env` file with random secrets
2. Build Docker containers (Postgres, API, Frontend)
3. Start all services
4. Prompt you to create an admin user and password

### Step 4: Ingest your PDFs

```bash
# Copy your PDF files into the folder
cp /path/to/your/*.pdf ~/Documents/rag-pdfs/

# Run ingestion to process and embed the PDFs
docker compose run --rm ingestion
```

### Step 5: Open the app

- **Chat interface:** http://localhost:3000
- **API:** http://localhost:8000
- **Health check:** http://localhost:8000/health

Log in with the credentials you created during setup and start asking questions.

---

## Setup — Windows

On Windows, Ollama runs natively and the Docker containers connect to it via `host.docker.internal`. If your machine has an NVIDIA GPU, Ollama will use it automatically for faster inference.

### Step 1: Install prerequisites

1. Install **Docker Desktop** from https://www.docker.com/products/docker-desktop/
2. Install **Ollama** from https://ollama.com/download/windows
3. Install **Git** from https://git-scm.com/download/win
4. Open Docker Desktop > **Settings > Resources** > set memory to **8 GB or higher**

### Step 2: Start Ollama and pull models

Open a terminal (PowerShell or Git Bash):

```powershell
# Ollama starts automatically after installation on Windows
# Pull the embedding model (~274 MB)
ollama pull nomic-embed-text

# Pull the LLM (~2 GB)
ollama pull llama3.2:3b
```

### Step 3: Clone and run the setup script

**Option A — PowerShell:**
```powershell
git clone https://github.com/AsrithVarma/POC_GroundHog-RAG.git
cd POC_GroundHog-RAG

# Create a folder for your PDFs
mkdir C:\rag-pdfs

# Run the setup script
.\scripts\setup.ps1 -DataPath "C:\rag-pdfs"
```

**Option B — Git Bash:**
```bash
git clone https://github.com/AsrithVarma/POC_GroundHog-RAG.git
cd POC_GroundHog-RAG

mkdir -p /c/rag-pdfs

bash scripts/setup.sh /c/rag-pdfs
```

The script will:
1. Generate a `.env` file with random secrets
2. Build Docker containers (Postgres, API, Frontend)
3. Start all services
4. Prompt you to create an admin user and password

### Step 4: Ingest your PDFs

```powershell
# Copy your PDF files into the folder
Copy-Item C:\path\to\your\*.pdf C:\rag-pdfs\

# Run ingestion to process and embed the PDFs
docker compose run --rm ingestion
```

### Step 5: Open the app

- **Chat interface:** http://localhost:3000
- **API:** http://localhost:8000
- **Health check:** http://localhost:8000/health

Log in with the credentials you created during setup and start asking questions.

---

## Clean Reset

If you need to start fresh (wipes the database, all users, and ingested documents):

```bash
docker compose down -v
rm .env

# macOS
bash scripts/setup.sh ~/Documents/rag-pdfs

# Windows (PowerShell)
.\scripts\setup.ps1 -DataPath "C:\rag-pdfs"
```

Then re-ingest your PDFs:
```bash
docker compose run --rm ingestion
```

---

## Usage

### Adding documents
1. Place PDFs in your `DATA_PATH` folder
2. Run ingestion: `docker compose run --rm ingestion`
3. Log out and log back in — documents appear in the sidebar

### Adding users
```bash
# Get the API container name
docker compose ps api

# Create a new user (roles: admin, analyst, viewer)
docker exec -it <api-container> python -m scripts.create_user \
    --username alice --access-group all --role analyst
```

### Access groups (RBAC)
Documents and users have an `access_group` field. Users can **only query documents in their group**. The user's access group must match the documents' access group exactly.

```bash
# Default ingestion uses access_group "all"
docker compose run --rm ingestion

# Ingest with a specific group
docker compose run --rm ingestion --access-group legal
docker compose run --rm ingestion --access-group engineering
```

When creating users, set their access group to match:
```bash
docker exec -it <api-container> python -m scripts.create_user \
    --username bob --access-group legal --role viewer
```

### Stopping and restarting
```bash
# Stop all containers (data is preserved)
docker compose down

# Start again
docker compose up -d
```

---

## Architecture

```
User -> Frontend (Streamlit :3000)
            |
            v
        API (FastAPI :8000)
            |
            ├──> PostgreSQL + pgvector (embeddings, metadata, RBAC)
            |
            └──> Ollama (native, on host machine)
                    ├── nomic-embed-text (query embedding)
                    └── llama3.2:3b (answer generation)
```

- **Ollama runs natively** on the host machine (not in Docker) for GPU access
- **PostgreSQL + pgvector** stores document chunks with HNSW-indexed embeddings
- **RBAC** — access groups control who sees what documents
- **Audit logging** — every query is logged with retrieved chunks and response
- **All ports bind to `127.0.0.1`** — not exposed to your network

### Performance optimizations
- **HNSW index** with `ef_construction=200` and `ef_search=100` for fast vector search
- **Persistent HTTP clients** — reused connections to Ollama (no per-request TCP overhead)
- **B-tree indexes** on `chunks(document_id)` and `documents(access_group)` for fast JOINs
- **Configurable via environment variables:** `HNSW_EF_SEARCH`, `MIN_SIMILARITY`, `LLM_MAX_TOKENS`, `LLM_NUM_CTX`

---

## Expected Performance

| Hardware | Embedding | DB Search | LLM Response | Total |
|---|---|---|---|---|
| Mac M1/M2/M3 (16 GB) | ~50ms | ~6ms | ~5-10 sec | **~10 sec** |
| Mac M4 Pro (36 GB) | ~30ms | ~6ms | ~2-5 sec | **~5 sec** |
| Windows with NVIDIA GPU | ~50ms | ~6ms | ~5-15 sec | **~15 sec** |
| Windows/Mac CPU only | ~300ms | ~45ms | ~60-120 sec | **~2 min** |

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_HOST` | `http://host.docker.internal:11434` | Ollama server URL |
| `LLM_MODEL` | `llama3.2:3b` | Ollama model for answer generation |
| `LLM_MAX_TOKENS` | `512` | Maximum tokens in LLM response |
| `LLM_NUM_CTX` | `2048` | Context window size for the LLM |
| `HNSW_EF_SEARCH` | `100` | HNSW search width (higher = better recall, slower) |
| `MIN_SIMILARITY` | `0.3` | Minimum cosine similarity threshold for retrieval |
| `DATA_PATH` | — | Full path to your PDF folder |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "No documents ingested yet" in sidebar | Access group mismatch. Check: `docker exec <postgres> psql -U raguser -d ragdb -c "SELECT DISTINCT access_group FROM documents;"` and make sure your user's group matches. |
| "I don't have enough information" on every query | PDFs not ingested. Run `docker compose run --rm ingestion`. |
| `password authentication failed` | Database volume has old password. Run `docker compose down -v` then `docker compose up -d`. |
| Ollama connection refused | Ollama not running. Start it: `ollama serve &` (Mac) or open Ollama app (Windows). |
| Slow responses (1-2 min) | Expected on CPU-only hardware. Use a Mac with Apple Silicon or a machine with an NVIDIA GPU for 5-10 second responses. |
| Ingestion says "Skipping (duplicate)" | PDFs already ingested. To re-ingest: `docker exec <postgres> psql -U raguser -d ragdb -c "TRUNCATE chunks, documents CASCADE;"` then `docker compose run --rm ingestion`. |
| Containers won't start | Run `docker compose logs` to see errors. Verify `.env` exists and has all required values. |
| Docker build fails (no internet) | Docker needs internet access to pull base images on first build. Ensure Docker Desktop has network access. |

## Security Notes

- `.env` contains secrets — never commit it to a public repo
- All ports bind to `127.0.0.1` only (not exposed to your network)
- PDF mount is read-only
- Logs never contain document text, queries, or embeddings
