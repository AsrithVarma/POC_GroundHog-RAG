# setup.ps1 — One-command setup for GroundHog RAG on Windows
# Run from the project root: .\scripts\setup.ps1

param(
    [string]$DataPath = "",
    [string]$Username = "admin",
    [string]$AccessGroup = "default",
    [string]$Role = "admin"
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host "`n>> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "   OK: $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "   WARN: $msg" -ForegroundColor Yellow }

Write-Host "============================================" -ForegroundColor White
Write-Host " GroundHog RAG — Setup Script" -ForegroundColor White
Write-Host "============================================" -ForegroundColor White

# -------------------------------------------------------
# Step 1: Check prerequisites
# -------------------------------------------------------
Write-Step "Checking prerequisites"

$docker = Get-Command docker -ErrorAction SilentlyContinue
if (-not $docker) {
    Write-Error "Docker is not installed. Install Docker Desktop from https://www.docker.com/products/docker-desktop/"
    exit 1
}
Write-Ok "Docker found"

$compose = docker compose version 2>$null
if (-not $compose) {
    Write-Error "Docker Compose not found. Ensure Docker Desktop is up to date."
    exit 1
}
Write-Ok "Docker Compose found"

# Check Docker is running
docker info > $null 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker is not running. Start Docker Desktop and try again."
    exit 1
}
Write-Ok "Docker is running"

# -------------------------------------------------------
# Step 2: Create .env file
# -------------------------------------------------------
Write-Step "Configuring environment"

if (Test-Path ".env") {
    Write-Warn ".env already exists — skipping (delete it first to regenerate)"
} else {
    # Prompt for data path if not provided
    if (-not $DataPath) {
        $DataPath = Read-Host "Enter the full path to your PDF folder (e.g., C:\Documents\pdfs)"
    }

    if (-not (Test-Path $DataPath)) {
        Write-Warn "Path '$DataPath' does not exist. Creating it..."
        New-Item -ItemType Directory -Path $DataPath -Force | Out-Null
    }

    # Generate random secrets
    $jwtSecret = -join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Max 256) })
    $encKey    = -join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Max 256) })
    $dbPass    = -join ((1..16) | ForEach-Object { "{0:x2}" -f (Get-Random -Max 256) })

    $envContent = @"
POSTGRES_PASSWORD=$dbPass
POSTGRES_USER=raguser
POSTGRES_DB=ragdb
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
OLLAMA_HOST=http://ollama:11434
JWT_SECRET=$jwtSecret
ENCRYPTION_KEY=$encKey
DATA_PATH=$DataPath
"@

    Set-Content -Path ".env" -Value $envContent
    Write-Ok ".env created with generated secrets"
}

# -------------------------------------------------------
# Step 3: Build and start services
# -------------------------------------------------------
Write-Step "Building and starting containers (this may take several minutes on first run)"

docker compose build
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed. Check the output above."
    exit 1
}
Write-Ok "Images built"

docker compose up -d postgres ollama
Write-Ok "Database and Ollama starting"

Write-Host "   Waiting for services to become healthy..." -ForegroundColor Gray
$timeout = 120
$elapsed = 0
while ($elapsed -lt $timeout) {
    $pgHealth = docker compose ps postgres --format "{{.Health}}" 2>$null
    $olHealth = docker compose ps ollama --format "{{.Health}}" 2>$null

    if ($pgHealth -match "healthy" -and $olHealth -match "healthy") {
        break
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
    Write-Host "   ... waiting ($elapsed`s)" -ForegroundColor Gray
}

if ($elapsed -ge $timeout) {
    Write-Warn "Services did not become healthy within ${timeout}s. Continuing anyway..."
} else {
    Write-Ok "PostgreSQL and Ollama are healthy"
}

# -------------------------------------------------------
# Step 4: Pull the LLM models into Ollama
# -------------------------------------------------------
Write-Step "Pulling AI models into Ollama (first time: ~2-4 GB download)"

$ollamaContainer = docker compose ps ollama --format "{{.Name}}" 2>$null
$ollamaContainer = $ollamaContainer.Trim()

# Temporarily connect Ollama to the internet-facing network for model download
Write-Host "   Connecting Ollama to external network for download..." -ForegroundColor Gray
$projectName = (docker inspect $ollamaContainer --format '{{index .Config.Labels "com.docker.compose.project"}}').Trim()
$extNetwork = "${projectName}_rag_ext"

docker network create $extNetwork 2>$null
docker network connect $extNetwork $ollamaContainer
Write-Ok "Ollama connected to external network"

Write-Host "   Pulling nomic-embed-text (embedding model)..." -ForegroundColor Gray
docker exec $ollamaContainer ollama pull nomic-embed-text
Write-Ok "nomic-embed-text ready"

Write-Host "   Pulling llama3.2:3b (language model)..." -ForegroundColor Gray
docker exec $ollamaContainer ollama pull llama3.2:3b
Write-Ok "llama3.2:3b ready"

# Disconnect from external network to restore air-gap
Write-Host "   Restoring air-gap (disconnecting Ollama from external network)..." -ForegroundColor Gray
docker network disconnect $extNetwork $ollamaContainer
Write-Ok "Air-gap restored"

# -------------------------------------------------------
# Step 5: Start remaining services
# -------------------------------------------------------
Write-Step "Starting API and frontend"

docker compose up -d
Write-Ok "All services started"

# -------------------------------------------------------
# Step 6: Create first user
# -------------------------------------------------------
Write-Step "Creating admin user"

Write-Host "   Creating user: $Username (role=$Role, group=$AccessGroup)" -ForegroundColor Gray

$apiContainer = docker compose ps api --format "{{.Name}}" 2>$null
$apiContainer = $apiContainer.Trim()

# Wait for API to be ready
Start-Sleep -Seconds 5

Write-Host "   You will be prompted to set a password:" -ForegroundColor Yellow
docker exec -it $apiContainer python -m scripts.create_user --username $Username --access-group $AccessGroup --role $Role

if ($LASTEXITCODE -eq 0) {
    Write-Ok "User '$Username' created"
} else {
    Write-Warn "User creation failed — you can create users later with:"
    Write-Host "   docker exec -it $apiContainer python -m scripts.create_user --username <name> --access-group <group> --role admin" -ForegroundColor Gray
}

# -------------------------------------------------------
# Done
# -------------------------------------------------------
Write-Host "`n============================================" -ForegroundColor Green
Write-Host " Setup Complete!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Frontend:  http://localhost:3000" -ForegroundColor White
Write-Host "  API:       http://localhost:8000" -ForegroundColor White
Write-Host "  Health:    http://localhost:8000/health" -ForegroundColor White
Write-Host ""
Write-Host "  PDF folder: $DataPath" -ForegroundColor Gray
Write-Host "  Place PDFs there, then run:" -ForegroundColor Gray
Write-Host "    docker compose run --rm ingestion" -ForegroundColor Gray
Write-Host ""
Write-Host "  To add more users:" -ForegroundColor Gray
Write-Host "    docker exec -it $apiContainer python -m scripts.create_user --username <name> --access-group <group> --role viewer" -ForegroundColor Gray
Write-Host ""
