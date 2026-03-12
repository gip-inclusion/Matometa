"""Watchdog agent configuration."""

import os

# --- LLM Backend ---
OLLAMA_API_KEY = os.environ.get("OLLAMA_API_KEY", "")
OLLAMA_API_URL = os.environ.get("OLLAMA_API_URL", "https://ollama.com")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen3-coder-next")

# --- Check intervals (seconds) ---
INTERVAL_CONTAINERS = int(os.environ.get("WATCHDOG_INTERVAL_CONTAINERS", "60"))
INTERVAL_STUCK_FLAGS = int(os.environ.get("WATCHDOG_INTERVAL_STUCK_FLAGS", "30"))
INTERVAL_DISK = int(os.environ.get("WATCHDOG_INTERVAL_DISK", "300"))
INTERVAL_SMOKE = int(os.environ.get("WATCHDOG_INTERVAL_SMOKE", "900"))
INTERVAL_AGENT_CYCLE = int(os.environ.get("WATCHDOG_INTERVAL_AGENT", "120"))

# --- Thresholds ---
DISK_WARN_PCT = int(os.environ.get("WATCHDOG_DISK_WARN_PCT", "80"))
DISK_CRITICAL_PCT = int(os.environ.get("WATCHDOG_DISK_CRITICAL_PCT", "90"))
RAM_WARN_PCT = int(os.environ.get("WATCHDOG_RAM_WARN_PCT", "15"))
RAM_CRITICAL_PCT = int(os.environ.get("WATCHDOG_RAM_CRITICAL_PCT", "10"))

# --- Circuit breaker ---
MAX_RESTARTS_PER_CONTAINER = 3
RESTART_WINDOW_MINUTES = 15

# --- Memory ---
MEMORY_FILE = os.environ.get("WATCHDOG_MEMORY_FILE", "/app/data/watchdog_memory.jsonl")
MEMORY_MAX_REPORTS = int(os.environ.get("WATCHDOG_MEMORY_MAX_REPORTS", "20"))
MEMORY_MAX_SIZE_KB = int(os.environ.get("WATCHDOG_MEMORY_MAX_SIZE_KB", "64"))

# --- Reporting ---
LOG_FILE = os.environ.get("WATCHDOG_LOG_FILE", "/app/data/watchdog.jsonl")
WEBHOOK_URL = os.environ.get("WATCHDOG_WEBHOOK_URL", "")

# --- Database ---
DATABASE_URL = os.environ.get("DATABASE_URL", "")
SQLITE_PATH = os.environ.get("WATCHDOG_SQLITE_PATH", "/app/data/matometa.db")

# --- Matometa ---
MATOMETA_BASE_URL = os.environ.get("MATOMETA_BASE_URL", "http://localhost:5000")
