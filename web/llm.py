"""Backend-agnostic LLM helpers for short prompts (titles, tags, etc.)."""

from __future__ import annotations

import logging
import subprocess
from typing import Optional

import requests

from . import config

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when an LLM backend fails or is misconfigured."""


def get_llm_backend() -> str:
    backend = (config.LLM_BACKEND or config.AGENT_BACKEND).lower()
    return backend


def generate_text(
    prompt: str,
    *,
    model: Optional[str] = None,
    max_tokens: int = 100,
    temperature: float = 0.2,
    timeout: Optional[float] = None,
) -> str:
    backend = get_llm_backend()

    if backend in ("ollama", "cli-ollama"):
        return ollama_generate(
            prompt,
            model=model or config.OLLAMA_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
        )

    if backend == "cli":
        return claude_cli_generate(
            prompt,
            timeout=timeout,
        )

    raise LLMError(f"Unsupported LLM backend: {backend}")


def ollama_generate(
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: Optional[float],
) -> str:
    base_url = config.OLLAMA_BASE_URL.rstrip("/")
    url = f"{base_url}/api/generate"
    timeout = timeout if timeout is not None else config.OLLAMA_REQUEST_TIMEOUT

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    try:
        response = requests.post(url, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        text = data.get("response", "")
        return text.strip()
    except requests.RequestException as exc:
        raise LLMError(f"Ollama request failed: {exc}") from exc


def claude_cli_generate(prompt: str, *, timeout: Optional[float]) -> str:
    timeout = timeout or 60
    try:
        result = subprocess.run(
            [config.CLAUDE_CLI, "--print", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(config.BASE_DIR),
        )
    except subprocess.TimeoutExpired as exc:
        raise LLMError("Claude CLI timed out") from exc
    except Exception as exc:
        raise LLMError(f"Claude CLI failed: {exc}") from exc

    if result.returncode != 0:
        raise LLMError(result.stderr.strip() or "Claude CLI error")

    return result.stdout.strip()
