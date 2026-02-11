"""Backend-agnostic LLM helpers for short prompts (titles, tags, etc.)."""

from __future__ import annotations

import logging
import os
import subprocess
from typing import Optional

import httpx

from . import config

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Raised when an LLM backend fails or is misconfigured."""


def _get_llm_backend() -> str:
    backend = (config.LLM_BACKEND or config.AGENT_BACKEND).lower()
    return backend


def generate_text(
    prompt: str,
    *,
    model: Optional[str] = None,
    max_tokens: int = 100,
    temperature: float = 0.2,
    timeout: Optional[float] = None,
    client: Optional[httpx.Client] = None,
) -> str:
    """Generate a short text completion using the configured backend."""
    backend = _get_llm_backend()

    if backend == "ollama":
        return _ollama_generate(
            prompt,
            model=model or config.OLLAMA_MODEL,
            max_tokens=max_tokens,
            temperature=temperature,
            timeout=timeout,
            client=client,
        )

    if backend == "sdk":
        return _anthropic_generate(
            prompt,
            model=model or config.CLAUDE_MODEL,
            max_tokens=max_tokens,
        )

    if backend == "cli":
        return _claude_cli_generate(
            prompt,
            timeout=timeout,
        )

    raise LLMError(f"Unsupported LLM backend: {backend}")


def _ollama_generate(
    prompt: str,
    *,
    model: str,
    max_tokens: int,
    temperature: float,
    timeout: Optional[float],
    client: Optional[httpx.Client],
) -> str:
    base_url = config.OLLAMA_BASE_URL.rstrip("/")
    url = f"{base_url}/api/generate"
    timeout = timeout or config.OLLAMA_REQUEST_TIMEOUT

    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    close_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)

    try:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        text = data.get("response", "")
        return text.strip()
    except httpx.HTTPError as exc:
        raise LLMError(f"Ollama request failed: {exc}") from exc
    finally:
        if close_client:
            client.close()


def _anthropic_generate(prompt: str, *, model: str, max_tokens: int) -> str:
    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise LLMError("anthropic package not installed") from exc

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("ANTHROPIC_API_KEY not set")

    client = Anthropic(api_key=api_key)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as exc:
        raise LLMError(f"Anthropic request failed: {exc}") from exc


def _claude_cli_generate(prompt: str, *, timeout: Optional[float]) -> str:
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
