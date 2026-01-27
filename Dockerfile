# Matometa - Analytics assistant web app
# Uses Claude Agent SDK for AI-powered analytics queries

FROM python:3.11-slim

# Install Node.js for Claude Code CLI
RUN apt-get update && apt-get install -y \
    curl \
    git \
    procps \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI globally
RUN npm install -g @anthropic-ai/claude-code

# Create non-root user (UID 1004 to match host for volume permissions)
RUN useradd -m -s /bin/bash -u 1004 matometa

# Set up app directory
WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=matometa:matometa . .

# Create data directory for SQLite
RUN mkdir -p /app/data && chown matometa:matometa /app/data

# Switch to non-root user
USER matometa

# Environment variables
ENV AGENT_BACKEND=sdk \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=5000 \
    WEB_DEBUG=false

EXPOSE 5000

CMD ["python", "-m", "web.app"]
