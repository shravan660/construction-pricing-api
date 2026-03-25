# Pricing Engine — one-command startup for Windows
# Usage: .\start.ps1
# Does: create venv → install deps → build index → start API

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "=== Pricing Engine Setup ===" -ForegroundColor Cyan

# 1. Create virtual environment if it doesn't exist
if (-not (Test-Path ".venv")) {
    Write-Host "> Creating virtual environment..." -ForegroundColor Yellow
    python -m venv .venv
}

# 2. Activate
Write-Host "> Activating virtual environment..." -ForegroundColor Yellow
& .\.venv\Scripts\Activate.ps1

# 3. Install dependencies
Write-Host "> Installing dependencies (this may take a few minutes on first run)..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet

# 4. Build FAISS index if not already built
if (-not (Test-Path "data\indexes\products.index")) {
    Write-Host "> Building vector index from seed data..." -ForegroundColor Yellow
    python scripts/build_index.py --use-seed
} else {
    Write-Host "> Vector index already exists, skipping build." -ForegroundColor Green
}

# 5. Start the API
Write-Host ""
Write-Host "=== Starting API on http://localhost:8000 ===" -ForegroundColor Green
Write-Host "    Docs: http://localhost:8000/docs" -ForegroundColor Green
Write-Host "    Press Ctrl+C to stop" -ForegroundColor Gray
Write-Host ""
uvicorn app.main:app --host 0.0.0.0 --port 8000
