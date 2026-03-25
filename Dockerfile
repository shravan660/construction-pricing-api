# ── Stage 1: dependency install (cached layer) ───────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

# System deps for playwright, lxml, faiss
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpangocairo-1.0-0 libpango-1.0-0 libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium (for the scraper)
RUN python -m playwright install chromium --with-deps || true

# ── Stage 2: application image ───────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Copy installed packages and playwright browsers from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /root/.cache/ms-playwright /root/.cache/ms-playwright

# Runtime system libraries (needed by Playwright / lxml)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libasound2 libpangocairo-1.0-0 libpango-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy application source
COPY . .

# Create data directories
RUN mkdir -p data/raw data/processed data/indexes

# Pre-build the FAISS index from seed data so the container starts ready
RUN python scripts/build_index.py --use-seed

EXPOSE 8000

# Entrypoint: warm-start uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
