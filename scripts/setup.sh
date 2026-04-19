#!/usr/bin/env bash
# setup.sh — One-command setup for GroundHog RAG on Linux/macOS/WSL
# Run from the project root: bash scripts/setup.sh

set -euo pipefail

DATA_PATH="${1:-}"
USERNAME="${2:-admin}"
ACCESS_GROUP="${3:-default}"
ROLE="${4:-admin}"

step()  { echo -e "\n\033[36m>> $1\033[0m"; }
ok()    { echo -e "   \033[32mOK: $1\033[0m"; }
warn()  { echo -e "   \033[33mWARN: $1\033[0m"; }

echo "============================================"
echo " GroundHog RAG — Setup Script"
echo "============================================"

# -------------------------------------------------------
# Step 1: Check prerequisites
# -------------------------------------------------------
step "Checking prerequisites"

[ -f "docker-compose.yml" ] || { echo "ERROR: docker-compose.yml not found in $(pwd). Run this script from the project root."; exit 1; }
ok "Project root verified"

command -v docker >/dev/null 2>&1 || { echo "ERROR: Docker not installed."; exit 1; }
ok "Docker found"

docker compose version >/dev/null 2>&1 || { echo "ERROR: Docker Compose not found."; exit 1; }
ok "Docker Compose found"

docker info >/dev/null 2>&1 || { echo "ERROR: Docker is not running."; exit 1; }
ok "Docker is running"

command -v openssl >/dev/null 2>&1 || { echo "ERROR: openssl not installed. Install it and retry."; exit 1; }
ok "openssl found"

# -------------------------------------------------------
# Step 2: Create .env file
# -------------------------------------------------------
step "Configuring environment"

if [ -f ".env" ]; then
    warn ".env already exists — skipping (delete it first to regenerate)"
else
    if [ -z "$DATA_PATH" ]; then
        read -rp "Enter the full path to your PDF folder: " DATA_PATH
    fi

    # Expand ~ to home directory
    DATA_PATH="${DATA_PATH/#\~/$HOME}"

    # Convert to absolute path if relative
    if [[ "$DATA_PATH" != /* ]]; then
        DATA_PATH="$(cd "$(dirname "$DATA_PATH")" 2>/dev/null && pwd)/$(basename "$DATA_PATH")"
    fi

    mkdir -p "$DATA_PATH"

    JWT_SECRET=$(openssl rand -hex 32)
    ENC_KEY=$(openssl rand -hex 32)
    DB_PASS=$(openssl rand -hex 16)

    cat > .env <<EOF
POSTGRES_PASSWORD=$DB_PASS
POSTGRES_USER=raguser
POSTGRES_DB=ragdb
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
OLLAMA_HOST=http://ollama:11434
JWT_SECRET=$JWT_SECRET
ENCRYPTION_KEY=$ENC_KEY
DATA_PATH=$DATA_PATH
EOF

    ok ".env created with generated secrets"
fi

# -------------------------------------------------------
# Step 3: Build and start services
# -------------------------------------------------------
step "Building and starting containers (this may take several minutes on first run)"

docker compose build
ok "Images built"

docker compose up -d postgres ollama
ok "Database and Ollama starting"

echo "   Waiting for services to become healthy..."
TIMEOUT=120
ELAPSED=0
while [ $ELAPSED -lt $TIMEOUT ]; do
    PG=$(docker compose ps postgres --format "{{.Health}}" 2>/dev/null || echo "")
    OL=$(docker compose ps ollama --format "{{.Health}}" 2>/dev/null || echo "")

    if [ -n "$PG" ] && echo "$PG" | grep -q "healthy" && [ -n "$OL" ] && echo "$OL" | grep -q "healthy"; then
        break
    fi
    sleep 5
    ELAPSED=$((ELAPSED + 5))
    echo "   ... waiting (${ELAPSED}s)"
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    warn "Services did not become healthy within ${TIMEOUT}s. Continuing..."
else
    ok "PostgreSQL and Ollama are healthy"
fi

# -------------------------------------------------------
# Step 4: Pull LLM models
# -------------------------------------------------------
step "Pulling AI models into Ollama (first time: ~2-4 GB download)"

OLLAMA_CONTAINER=$(docker compose ps ollama --format "{{.Name}}" | head -1)

if [ -z "$OLLAMA_CONTAINER" ]; then
    echo "ERROR: Ollama container not found. Check 'docker compose ps' output."
    exit 1
fi

# Temporarily connect Ollama to the internet-facing network for model download
echo "   Connecting Ollama to external network for download..."
PROJECT_NAME=$(docker inspect "$OLLAMA_CONTAINER" --format '{{index .Config.Labels "com.docker.compose.project"}}')

if [ -z "$PROJECT_NAME" ] || [ "$PROJECT_NAME" = "<no value>" ]; then
    echo "ERROR: Could not determine Docker Compose project name from container labels."
    exit 1
fi

EXT_NETWORK="${PROJECT_NAME}_rag_ext"

docker network create \
  --label "com.docker.compose.network=rag_ext" \
  --label "com.docker.compose.project=$PROJECT_NAME" \
  "$EXT_NETWORK" 2>/dev/null || true
docker network connect "$EXT_NETWORK" "$OLLAMA_CONTAINER" 2>/dev/null || true
ok "Ollama connected to external network"

echo "   Pulling nomic-embed-text (this may take a few minutes)..."
timeout 600 docker exec "$OLLAMA_CONTAINER" ollama pull nomic-embed-text || \
    { warn "nomic-embed-text pull timed out or failed. Retry manually: docker exec $OLLAMA_CONTAINER ollama pull nomic-embed-text"; exit 1; }
ok "nomic-embed-text ready"

echo "   Pulling llama3.2:3b (this may take several minutes)..."
timeout 600 docker exec "$OLLAMA_CONTAINER" ollama pull llama3.2:3b || \
    { warn "llama3.2:3b pull timed out or failed. Retry manually: docker exec $OLLAMA_CONTAINER ollama pull llama3.2:3b"; exit 1; }
ok "llama3.2:3b ready"

# Disconnect from external network to restore air-gap
echo "   Restoring air-gap (disconnecting Ollama from external network)..."
docker network disconnect "$EXT_NETWORK" "$OLLAMA_CONTAINER" 2>/dev/null || true
ok "Air-gap restored"

# -------------------------------------------------------
# Step 5: Start remaining services
# -------------------------------------------------------
step "Starting API and frontend"

docker compose up -d
ok "All services started"

# -------------------------------------------------------
# Step 6: Create first user
# -------------------------------------------------------
step "Creating admin user"

API_CONTAINER=$(docker compose ps api --format "{{.Name}}" | head -1)

if [ -z "$API_CONTAINER" ]; then
    warn "API container not found. Create users later after services are running."
else
    # Wait for API to be ready (check health endpoint)
    echo "   Waiting for API to be ready..."
    API_READY=0
    for i in $(seq 1 12); do
        if docker exec "$API_CONTAINER" python -c "import httpx; httpx.get('http://localhost:8000/health')" >/dev/null 2>&1; then
            API_READY=1
            break
        fi
        sleep 5
        echo "   ... waiting (${i}0s)"
    done

    if [ $API_READY -eq 0 ]; then
        warn "API did not become ready. Create users later with:"
        warn "  docker exec -it \"$API_CONTAINER\" python -m scripts.create_user --username <name> --access-group <group> --role admin"
    else
        echo "   You will be prompted to set a password:"
        if [ -t 0 ]; then
            docker exec -it "$API_CONTAINER" python -m scripts.create_user \
                --username "$USERNAME" --access-group "$ACCESS_GROUP" --role "$ROLE" || \
                warn "User creation failed — create users later with: docker exec -it \"$API_CONTAINER\" python -m scripts.create_user --username <name> --access-group <group> --role admin"
        else
            warn "Non-interactive shell detected. Create users manually:"
            warn "  docker exec -it \"$API_CONTAINER\" python -m scripts.create_user --username \"$USERNAME\" --access-group \"$ACCESS_GROUP\" --role \"$ROLE\""
        fi
    fi
fi

# -------------------------------------------------------
# Done
# -------------------------------------------------------
echo ""
echo -e "\033[32m============================================\033[0m"
echo -e "\033[32m Setup Complete!\033[0m"
echo -e "\033[32m============================================\033[0m"
echo ""
echo "  Frontend:  http://localhost:3000"
echo "  API:       http://localhost:8000"
echo "  Health:    http://localhost:8000/health"
echo ""
echo "  PDF folder: $DATA_PATH"
echo "  Place PDFs there, then run:"
echo "    docker compose run --rm ingestion"
echo ""
echo "  To add more users:"
echo "    docker exec -it \"${API_CONTAINER:-<api-container>}\" python -m scripts.create_user --username <name> --access-group <group> --role viewer"
echo ""
