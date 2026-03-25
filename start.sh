#!/bin/bash
# Pricing Engine — one-command startup for macOS / Linux
# Usage: ./start.sh
# Does: create venv → install deps → build index → start API

set -e

echo ""
echo "=== Pricing Engine Setup ==="

# 1. Create virtual environment if it doesn't exist
if [ ! -d ".venv" ]; then
    echo "> Creating virtual environment..."
    python3 -m venv .venv
fi

# 2. Activate
echo "> Activating virtual environment..."
source .venv/bin/activate

# 3. Install dependencies
echo "> Installing dependencies (this may take a few minutes on first run)..."
pip install -r requirements.txt --quiet

# 4. Build FAISS index if not already built
if [ ! -f "data/indexes/products.index" ]; then
    echo "> Building vector index from seed data..."
    python scripts/build_index.py --use-seed
else
    echo "> Vector index already exists, skipping build."
fi

# 5. Start the API
echo ""
echo "=== Starting API on http://localhost:8000 ==="
echo "    Docs: http://localhost:8000/docs"
echo "    Press Ctrl+C to stop"
echo ""
uvicorn app.main:app --host 0.0.0.0 --port 8000
