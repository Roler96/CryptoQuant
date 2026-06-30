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

# Create runtime directories
RUN mkdir -p /app/data /app/logs /app/state

# Health check
HEALTHCHECK --interval=60s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run live trader
CMD ["uv", "run", "python", "live_runner.py"]
