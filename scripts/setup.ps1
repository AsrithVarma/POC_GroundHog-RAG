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

if (-not (Test-Path "docker-compose.yml")) {
    Write-Error "docker-compose.yml not found in $(Get-Location). Run this script from the project root."
    exit 1
}
Write-Ok "Project root verified"

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

    # Convert to absolute path
    $DataPath = [System.IO.Path]::GetFullPath($DataPath)

    if (-not (Test-Path $DataPath)) {
        Write-Warn "Path '$DataPath' does not exist. Creating it..."
        New-Item -ItemType Directory -Path $DataPath -Force | Out-Null
    }

    # Convert backslashes to forward slashes for Docker volume mounts
    $dockerDataPath = $DataPath -replace '\\', '/'

    # Generate cryptographically secure random secrets
    $rng = [System.Security.Cryptography.RNGCryptoServiceProvider]::new()
    function Get-SecureHex([int]$bytes) {
        $buf = New-Object byte[] $bytes
        $rng.GetBytes($buf)
        return ($buf | ForEach-Object { "{0:x2}" -f $_ }) -join ''
    }

    $jwtSecret = Get-SecureHex 32
    $encKey    = Get-SecureHex 32
    $dbPass    = Get-SecureHex 16

    $envContent = @"
POSTGRES_PASSWORD=$dbPass
POSTGRES_USER=raguser
POSTGRES_DB=ragdb
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
OLLAMA_HOST=http://host.docker.internal:11434
JWT_SECRET=$jwtSecret
ENCRYPTION_KEY=$encKey
DATA_PATH=$dockerDataPath
"@

    Set-Content -Path ".env" -Value $envContent -NoNewline
    Write-Ok ".env created with generated secrets"
}

# -------------------------------------------------------
# Step 3: Install and start Ollama natively (GPU access)
# -------------------------------------------------------
Write-Step "Setting up Ollama (native install for GPU acceleration)"

$ollamaCmd = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaCmd) {
    Write-Ok "Ollama already installed"
} else {
    Write-Host "   Installing Ollama..." -ForegroundColor Gray
    Write-Host "   Download and install from: https://ollama.com/download/windows" -ForegroundColor Yellow
    Write-Host "   After installing, re-run this script." -ForegroundColor Yellow
    exit 1
}

# Start Ollama if not already running
try {
    $null = Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 3
    Write-Ok "Ollama is running"
} catch {
    Write-Host "   Starting Ollama server..." -ForegroundColor Gray
    Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden
    Start-Sleep -Seconds 3
    Write-Ok "Ollama started"
}

# -------------------------------------------------------
# Step 4: Pull the LLM models
# -------------------------------------------------------
Write-Step "Pulling AI models (first time: ~2-4 GB download)"

Write-Host "   Pulling nomic-embed-text (this may take a few minutes)..." -ForegroundColor Gray
ollama pull nomic-embed-text
if ($LASTEXITCODE -ne 0) {
    Write-Error "nomic-embed-text pull failed. Check your internet connection and retry: ollama pull nomic-embed-text"
    exit 1
}
Write-Ok "nomic-embed-text ready"

Write-Host "   Pulling llama3.2:3b (this may take several minutes)..." -ForegroundColor Gray
ollama pull llama3.2:3b
if ($LASTEXITCODE -ne 0) {
    Write-Error "llama3.2:3b pull failed. Check your internet connection and retry: ollama pull llama3.2:3b"
    exit 1
}
Write-Ok "llama3.2:3b ready"

# -------------------------------------------------------
# Step 5: Build and start Docker services
# -------------------------------------------------------
Write-Step "Building and starting containers (this may take several minutes on first run)"

docker compose build
if ($LASTEXITCODE -ne 0) {
    Write-Error "Docker build failed. Check the output above."
    exit 1
}
Write-Ok "Images built"

docker compose up -d postgres
Write-Ok "Database starting"

Write-Host "   Waiting for PostgreSQL to become healthy..." -ForegroundColor Gray
$timeout = 120
$elapsed = 0
while ($elapsed -lt $timeout) {
    $pgHealth = docker compose ps postgres --format "{{.Health}}" 2>$null

    if ($pgHealth -and $pgHealth -match "healthy") {
        break
    }
    Start-Sleep -Seconds 5
    $elapsed += 5
    Write-Host "   ... waiting ($elapsed`s)" -ForegroundColor Gray
}

if ($elapsed -ge $timeout) {
    Write-Warn "PostgreSQL did not become healthy within ${timeout}s. Continuing anyway..."
} else {
    Write-Ok "PostgreSQL is healthy"
}

# -------------------------------------------------------
# Step 6: Start remaining services
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
if ($apiContainer) { $apiContainer = $apiContainer.Trim() }

if (-not $apiContainer) {
    Write-Warn "API container not found. Create users later after services are running."
} else {
    # Wait for API to be ready
    Write-Host "   Waiting for API to be ready..." -ForegroundColor Gray
    $apiReady = $false
    for ($i = 1; $i -le 12; $i++) {
        $healthCheck = docker exec $apiContainer python -c "import httpx; httpx.get('http://localhost:8000/health')" 2>$null
        if ($LASTEXITCODE -eq 0) {
            $apiReady = $true
            break
        }
        Start-Sleep -Seconds 5
        Write-Host "   ... waiting ($($i * 5)s)" -ForegroundColor Gray
    }

    if (-not $apiReady) {
        Write-Warn "API did not become ready. Create users later with:"
        Write-Host "   docker exec -it $apiContainer python -m scripts.create_user --username <name> --access-group <group> --role admin" -ForegroundColor Gray
    } else {
        Write-Host "   You will be prompted to set a password:" -ForegroundColor Yellow
        docker exec -it $apiContainer python -m scripts.create_user --username $Username --access-group $AccessGroup --role $Role

        if ($LASTEXITCODE -eq 0) {
            Write-Ok "User '$Username' created"
        } else {
            Write-Warn "User creation failed — you can create users later with:"
            Write-Host "   docker exec -it $apiContainer python -m scripts.create_user --username <name> --access-group <group> --role admin" -ForegroundColor Gray
        }
    }
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
$displayContainer = if ($apiContainer) { $apiContainer } else { "<api-container>" }
Write-Host "    docker exec -it $displayContainer python -m scripts.create_user --username <name> --access-group <group> --role viewer" -ForegroundColor Gray
Write-Host ""
