# Autometa - Analytics assistant web app

FROM python:3.11-slim

# Install Node.js for Claude Code CLI and ClamAV for file scanning
RUN apt-get update && apt-get install -y \
    curl \
    git \
    procps \
    clamav \
    clamav-daemon \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Update ClamAV virus definitions (run as root before switching user)
# Use freshclam with no-daemon mode; allow failure if network unavailable during build
RUN freshclam --no-dns || echo "Warning: Could not update ClamAV definitions during build"

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Create non-root user (UID 1004 to match host for volume permissions)
RUN useradd -m -s /bin/bash -u 1004 autometa

# Set up app directory
WORKDIR /app

# Install uv (fast Python package manager)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_SYSTEM_PYTHON=1 UV_COMPILE_BYTECODE=1

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock .python-version ./

# Install CPU-only PyTorch (server has no GPU).
# Avoids pulling ~7GB of CUDA/nvidia libraries.
# Local dev on macOS gets MPS support from the default torch wheel.
RUN uv pip install --no-cache torch --index-url https://download.pytorch.org/whl/cpu

# Install all dependencies including embeddings group.
# Filter out torch/nvidia (CPU-only torch already installed above).
RUN uv export --frozen --group embeddings --no-hashes | \
    grep -v '^\(torch\|nvidia-\|cuda-\)' | \
    uv pip install --no-cache -r -

# Copy application code
COPY --chown=autometa:autometa . .

# Create data directories for uploads and modified files
RUN mkdir -p /app/data /app/data/uploads /app/data/modified \
    && chown autometa:autometa /app/data /app/data/uploads /app/data/modified

# Switch to non-root user
USER autometa

# Environment variables
ENV AGENT_BACKEND=sdk \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=5000 \
    WEB_DEBUG=false

EXPOSE 5000

CMD ["./entrypoint.sh"]
