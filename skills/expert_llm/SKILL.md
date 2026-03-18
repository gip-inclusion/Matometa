# expert_llm — LLM integration for expert-mode apps

## When to use

Use this skill when building an expert-mode app that needs LLM capabilities:
agent, chatbot, AI assistant, conversational UI, text generation, summarization,
or any feature requiring language model inference.

**Trigger keywords in spec/description**: agent, chat, chatbot, assistant, LLM,
AI, conversational, generate text, summarize, NLP, RAG, embeddings.

## Backend

All expert-mode apps use **Synthetic** — an OpenAI-compatible API.

| Env var | Value |
|---------|-------|
| `SYNTHETIC_API_URL` | `https://api.synthetic.new/openai/v1` |
| `SYNTHETIC_API_KEY` | Injected at deploy time (never hardcode) |

These env vars are automatically injected into containers by the Docker deployment pipeline.

## Code templates

### Python (recommended)

```python
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
```

### JavaScript/Node

```javascript
// llm.js — LLM client (Synthetic, OpenAI-compatible)
const SYNTHETIC_API_URL = process.env.SYNTHETIC_API_URL || 'https://api.synthetic.new/openai/v1';
const SYNTHETIC_API_KEY = process.env.SYNTHETIC_API_KEY || '';
const DEFAULT_MODEL = process.env.LLM_MODEL || 'hf:meta-llama/Llama-3.2-3B-Instruct';

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
```

## Scaffold command

Generate the helper file in one command:

```bash
python -m skills.expert_llm.scripts.scaffold_llm --workdir <project-workdir>
# or for Node:
python -m skills.expert_llm.scripts.scaffold_llm --workdir <project-workdir> --lang node
```

## Guidelines for the coding assistant

1. **Generate an `llm.py` (or `llm.js`)** in the app that reads `SYNTHETIC_API_URL` and `SYNTHETIC_API_KEY` from env vars. Never hardcode.
2. **Add `requests` to requirements** if the app uses Python.
3. **Default model**: `hf:meta-llama/Llama-3.2-3B-Instruct` for general tasks. Use `hf:Qwen/Qwen2.5-Coder-14B-Instruct` for code-heavy tasks.
4. **Streaming**: set `"stream": true` in the request body and consume standard SSE.
5. **Dockerfile**: Do NOT bundle API keys. They come from env vars at runtime.
6. **docker-compose.yml**: Do NOT add `SYNTHETIC_API_KEY` to compose — it is injected by the deployment pipeline.
