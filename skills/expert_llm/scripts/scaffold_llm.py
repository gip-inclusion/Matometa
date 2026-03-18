"""Scaffold an llm.py helper into an expert-mode project.

Usage:
    python -m skills.expert_llm.scripts.scaffold_llm --workdir <project-workdir> [--lang python|node]
"""

from __future__ import annotations

import argparse
from pathlib import Path

PYTHON_TEMPLATE = '''\
"""llm.py — LLM client for this app. Uses Synthetic (OpenAI-compatible API)."""

import os
import requests

SYNTHETIC_API_URL = os.getenv("SYNTHETIC_API_URL", "https://api.synthetic.new/openai/v1")
SYNTHETIC_API_KEY = os.getenv("SYNTHETIC_API_KEY", "")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "hf:meta-llama/Llama-3.2-3B-Instruct")


def chat(
    messages: list[dict],
    model: str | None = None,
    timeout: int = 120,
) -> str:
    """Send a chat request. Returns the assistant message."""
    resp = requests.post(
        f"{SYNTHETIC_API_URL}/chat/completions",
        headers={"Authorization": f"Bearer {SYNTHETIC_API_KEY}"},
        json={
            "model": model or DEFAULT_MODEL,
            "messages": messages,
            "stream": False,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
'''

NODE_TEMPLATE = '''\
// llm.js — LLM client (Synthetic, OpenAI-compatible)
const SYNTHETIC_API_URL = process.env.SYNTHETIC_API_URL || 'https://api.synthetic.new/openai/v1';
const SYNTHETIC_API_KEY = process.env.SYNTHETIC_API_KEY || '';
const DEFAULT_MODEL = process.env.LLM_MODEL || 'hf:meta-llama/Llama-3.2-3B-Instruct';

/**
 * Send a chat request to the LLM.
 * @param {Array<{role: string, content: string}>} messages
 * @param {string} [model]
 * @returns {Promise<string>} The assistant message content.
 */
export async function chat(messages, model) {
  const res = await fetch(`${SYNTHETIC_API_URL}/chat/completions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${SYNTHETIC_API_KEY}`,
    },
    body: JSON.stringify({ model: model || DEFAULT_MODEL, messages, stream: false }),
  });
  if (!res.ok) throw new Error(`LLM error: ${res.status}`);
  const data = await res.json();
  return data.choices[0].message.content;
}
'''


def scaffold(workdir: str, lang: str = "python") -> str:
    """Write the LLM helper file into the project. Returns the created file path."""
    root = Path(workdir)
    if lang == "node":
        target = root / "llm.js"
        target.write_text(NODE_TEMPLATE)
    else:
        target = root / "llm.py"
        target.write_text(PYTHON_TEMPLATE)
    return str(target)


def main():
    parser = argparse.ArgumentParser(description="Scaffold LLM helper into a project")
    parser.add_argument("--workdir", required=True, help="Project working directory")
    parser.add_argument("--lang", choices=["python", "node"], default="python")
    args = parser.parse_args()

    path = scaffold(args.workdir, args.lang)
    print(f"Created {path}")


if __name__ == "__main__":
    main()
