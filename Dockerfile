# CryptoQuant Docker Image
# Build: docker build -t cryptoquant .
# Run:   docker run -d --name cryptoquant -v $(pwd)/data:/app/data -v $(pwd)/logs:/app/logs -v $(pwd)/state:/app/state --env-file .env cryptoquant
FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install --no-cache-dir uv

# Copy dependency manifests
COPY pyproject.toml ./
COPY uv.lock* ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY cryptoquant/ cryptoquant/
COPY strategies/ strategies/
COPY config.yaml ./
COPY live_runner.py ./
COPY deploy/healthcheck.py deploy/healthcheck.py

# Create runtime directories
RUN mkdir -p /app/data /app/logs /app/state

# Run as non-root user
RUN useradd -m -s /bin/bash app && chown -R app:app /app
USER app
ENV PATH="/app/.venv/bin:$PATH"

# Health check — verifies state file freshness (engine alive = state saves periodically)
HEALTHCHECK --interval=60s --timeout=10s --retries=3 --start-period=180s \
    CMD python deploy/healthcheck.py

# Run live trader
CMD ["python", "live_runner.py"]
