# Matometa - Analytics assistant web app
# Uses Claude Agent SDK for AI-powered analytics queries

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
RUN useradd -m -s /bin/bash -u 1004 matometa

# Set up app directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .

# Install CPU-only PyTorch (server has no GPU).
# Avoids pulling ~7GB of CUDA/nvidia libraries.
# Local dev on macOS gets MPS support from the default torch wheel.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=matometa:matometa . .

# Create data directories for SQLite, uploads, and modified files
RUN mkdir -p /app/data /app/data/uploads /app/data/modified \
    && chown matometa:matometa /app/data /app/data/uploads /app/data/modified

# Entrypoint cleans stale SQLite WAL/SHM files left by other host users
COPY --chown=matometa:matometa entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Switch to non-root user
USER matometa

# Environment variables
ENV AGENT_BACKEND=sdk \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=5000 \
    WEB_DEBUG=false

EXPOSE 5000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["python", "-m", "web.app"]
