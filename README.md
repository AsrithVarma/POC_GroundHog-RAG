# GroundHog RAG — Private Document Q&A System

A fully self-hosted, air-gapped RAG (Retrieval-Augmented Generation) system. Ask questions about your PDF documents and get cited answers — nothing leaves your network.

## Prerequisites

- **Docker Desktop** (with Docker Compose v2)
- **8 GB+ RAM** available for containers (Ollama needs ~6 GB for the LLM)
- **10 GB disk space** for Docker images and AI models
- PDF documents you want to query

## Quick Start (5 minutes)

### Windows (PowerShell)
```powershell
.\scripts\setup.ps1
```

### Linux / macOS / WSL
```bash
bash scripts/setup.sh
```

The setup script will:
1. Check Docker is installed and running
2. Generate a `.env` file with random secrets
3. Build all containers
4. Pull AI models (~2-4 GB download, one-time)
5. Start all services
6. Create your first admin user

## Manual Setup

If you prefer to set things up step by step:

### 1. Configure environment
```bash
cp .env.template .env
```
Edit `.env` and set:
- `POSTGRES_PASSWORD` — a strong database password
- `JWT_SECRET` — a random 64-char hex string (`openssl rand -hex 32`)
- `ENCRYPTION_KEY` — a random 64-char hex string
- `DATA_PATH` — full path to your PDF folder (e.g., `C:\Documents\pdfs`)

### 2. Build and start
```bash
docker compose up -d
```

### 3. Pull AI models (first time only)
```bash
docker exec -it $(docker compose ps ollama --format "{{.Name}}") ollama pull nomic-embed-text
docker exec -it $(docker compose ps ollama --format "{{.Name}}") ollama pull llama3.2:3b
```

### 4. Create a user
```bash
docker exec -it $(docker compose ps api --format "{{.Name}}") python -m scripts.create_user \
    --username admin --access-group default --role admin
```

### 5. Ingest your PDFs
Place PDF files in your `DATA_PATH` folder, then:
```bash
docker compose run --rm ingestion
```

### 6. Open the app
- **Frontend:** http://localhost:3000
- **API:** http://localhost:8000
- **Health check:** http://localhost:8000/health

## Usage

### Adding documents
1. Place PDFs in your `DATA_PATH` folder
2. Run ingestion: `docker compose run --rm ingestion`
3. Documents appear in the sidebar after refresh

### Adding users
```bash
# Roles: admin, analyst, viewer
docker exec -it <api-container> python -m scripts.create_user \
    --username alice --access-group legal --role analyst
```

### Access groups (RBAC)
Documents and users have an `access_group` field. Users can only query documents in their group. Use this to separate departments:
```bash
# Ingest with a specific group
docker compose run --rm ingestion --access-group legal
docker compose run --rm ingestion --access-group engineering
```

### Dry run (test without writing to DB)
```bash
docker compose run --rm ingestion --dry-run
```

## Architecture

```
User → Nginx (TLS) → Frontend (Streamlit :3000)
                   → API (FastAPI :8000)
                        ├→ PostgreSQL + pgvector (embeddings + metadata)
                        └→ Ollama (nomic-embed-text + llama3.2:3b)
```

- **All AI runs locally** — Ollama handles both embeddings and text generation
- **Air-gapped backend** — PostgreSQL, Ollama, and ingestion are on an internal Docker network with no internet access
- **RBAC** — access groups control who sees what documents
- **Audit logging** — every query is logged with retrieved chunks and response

## Sharing This Project

### Option A: Git repository
```bash
git init
git add -A
git commit -m "Initial GroundHog RAG setup"
git remote add origin <your-repo-url>
git push -u origin main
```
The recipient clones and runs `.\scripts\setup.ps1` or `bash scripts/setup.sh`.

### Option B: Zip file
Zip the entire project folder (the `.gitignore` ensures `.env` and data files are excluded). Share the zip. The recipient extracts and runs the setup script.

### Option C: USB / air-gapped transfer
For fully offline deployment:
1. On an internet-connected machine, run setup once to pull all Docker images and models
2. Save images: `docker save pgvector/pgvector:pg16 ollama/ollama:latest | gzip > images.tar.gz`
3. Save model volume: `docker run --rm -v jsa_ollama_models:/data -v $(pwd):/backup alpine tar czf /backup/ollama_models.tar.gz -C /data .`
4. Transfer project folder + `images.tar.gz` + `ollama_models.tar.gz` via USB
5. On the target machine:
   ```bash
   docker load < images.tar.gz
   docker compose up -d ollama
   docker run --rm -v jsa_ollama_models:/data -v $(pwd):/backup alpine tar xzf /backup/ollama_models.tar.gz -C /data
   bash scripts/setup.sh
   ```

## Troubleshooting

| Problem | Fix |
|---|---|
| "I don't have enough information" on every query | Models may not be pulled. Run `docker exec <ollama> ollama list` to check. |
| Ingestion hangs | Ollama may be out of memory. Check `docker logs <ollama>`. Ensure 8 GB+ RAM available. |
| Login fails | Ensure user was created: `docker exec <api> python -m scripts.create_user ...` |
| Containers won't start | Run `docker compose logs` to see errors. Check `.env` values. |
| Slow responses | Expected on CPU. llama3.2:3b takes 30-120s per response depending on hardware. |

## Security Notes

- `.env` contains secrets — never commit it to a public repo
- All ports bind to `127.0.0.1` only (not exposed to your network)
- Backend services have no internet access
- PDF mount is read-only
- Logs never contain document text, queries, or embeddings
