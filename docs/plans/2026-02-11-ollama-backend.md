# Plan: Add Ollama as Agent Backend

## Goal

Add an Ollama backend as a fourth option alongside Claude CLI, SDK, and (planned)
ADK backends, enabling open-source models (Qwen3, Llama 3.3, DeepSeek, Mistral,
etc.) to power the Matometa agent with the same web UI and tool ecosystem.

## Why Ollama

- **Open source models**: Run agents with no proprietary API keys. Useful for
  testing, development, cost control, and environments where data cannot leave
  the network.
- **Self-hosted**: Ollama runs locally or on an internal server. No external API
  calls for model inference.
- **Tool calling support**: Ollama v0.4+ supports function/tool calling with
  streaming, compatible with models like Qwen3, Llama 3.1/3.3, Mistral, and
  DeepSeek-R1.

## Architecture Overview

```
AgentBackend (abstract base class)
├── CLIBackend   → spawns `claude` CLI process
├── SDKBackend   → uses claude-agent-sdk Python package
├── ADKBackend   → (planned) uses google-adk Python package
└── OllamaBackend → NEW: uses ollama Python package
```

All backends yield `AgentMessage` objects, streamed to the frontend via SSE.

## Library Choice: `ollama` (native Python client)

**Selected**: [`ollama`](https://github.com/ollama/ollama-python) v0.6.1+

**Alternatives considered:**

| Library | Pros | Cons |
|---------|------|------|
| `ollama` (native) | Direct async support, auto-schema from Python functions, best feature coverage, minimal deps | No built-in agent loop |
| `litellm` | Unified API across providers, OpenAI-compatible | Known bugs with Ollama streaming+tools+async (2025), extra abstraction layer |
| `openai` (compat endpoint) | Familiar API, could share code with future OpenAI backend | Ollama's `/v1/` endpoint has incomplete streaming tool call support |

The native `ollama` library is the best fit because:
1. It auto-generates tool schemas from Python function signatures + docstrings
   (same approach as ADK's `FunctionTool`)
2. `AsyncClient` supports `chat()` with `tools=` and `stream=True`
3. Minimal dependency footprint
4. Most direct path — no translation layers

## Design Decisions

### 1. Agent loop: Self-managed

Unlike Claude SDK (which runs its own agent loop) or ADK (which has `Runner`),
Ollama is a raw chat completion API. **We must implement the agent loop ourselves.**

```
while True:
    response = await ollama.chat(model, messages, tools, stream=True)
    if response has tool_calls:
        execute tools
        append tool results to messages
        continue
    else:
        break  # model is done
```

This is straightforward and gives us full control over tool execution, timeouts,
and cancellation.

### 2. Tool approach: Hybrid (same as ADK design)

- **Direct function tools** from MatomoAPI/MetabaseAPI (Ollama auto-converts
  Python functions with docstrings to JSON schemas)
- **Code execution tool** for advanced scripts (subprocess-based Python exec)
- **File reading tools** for knowledge base access

We reuse the same `web/agents/ollama_tools.py` module structure from the ADK
design, adapted for Ollama's function format.

### 3. Session management: Message history (no native sessions)

Ollama has no built-in session/conversation resumption. Instead:
- We pass the full message history as `messages` to each `chat()` call
- The existing database already stores all messages per conversation
- The `session_id` parameter in `send_message()` is ignored (not applicable)
- History truncation is applied to avoid exceeding context windows

This is simpler than the CLI/SDK session management and has the advantage of
being fully stateless on the Ollama side.

### 4. Model configuration

- `OLLAMA_MODEL` env var (default: `qwen3:32b`)
- `OLLAMA_HOST` env var (default: `http://localhost:11434`) — already the
  standard Ollama env var
- `OLLAMA_NUM_CTX` env var (default: `32768`) — context window size
- No UI changes needed

### 5. System prompt adaptation

AGENTS.md works as the system message. However, the tool-calling section needs
adaptation since tools are called differently:
- Claude: `Skill(matomo_query)` → runs a skill subprocess
- Ollama: `matomo_get_visits(site_id=117, ...)` → direct function call

We prepend a short adapter preamble to the system prompt explaining the available
tools and how to use them, while keeping the domain knowledge from AGENTS.md.

### 6. Streaming behavior

Ollama streams text tokens incrementally. During tool call resolution:
1. The model generates a `tool_calls` response (may not stream incrementally)
2. We execute the tools and yield `tool_use` + `tool_result` events
3. We call `chat()` again with the results appended
4. The model streams its next response

This matches the existing frontend expectations: `assistant` → `tool_use` →
`tool_result` → `assistant` → ...

### 7. Thinking/reasoning support

Models like Qwen3 and DeepSeek-R1 support "thinking" mode. When `think=True`:
- The model returns `message.thinking` content (chain-of-thought)
- We can optionally emit this as a `system` event for debugging
- The `think` parameter is configurable via `OLLAMA_THINK` env var

---

## Implementation Steps

### Step 1: Add ollama dependency

**File:** `requirements.txt`

Add:
```
# Ollama (local LLM backend)
ollama>=0.6.1
```

### Step 2: Add Ollama environment variables

**File:** `.env.example`

```bash
# Ollama backend settings
# OLLAMA_HOST=http://localhost:11434  # Ollama server URL (standard Ollama env var)
# OLLAMA_MODEL=qwen3:32b             # Model to use for agent
# OLLAMA_NUM_CTX=32768               # Context window size
# OLLAMA_THINK=false                  # Enable thinking/reasoning mode
# OLLAMA_MAX_TOOL_ROUNDS=20          # Max tool call rounds before stopping
```

**File:** `docker-compose.yml`

Add to environment section:
```yaml
- OLLAMA_HOST=${OLLAMA_HOST:-http://host.docker.internal:11434}
- OLLAMA_MODEL=${OLLAMA_MODEL:-qwen3:32b}
- OLLAMA_NUM_CTX=${OLLAMA_NUM_CTX:-32768}
```

### Step 3: Create Ollama tool registry

**File:** `web/agents/ollama_tools.py` (new file)

Adapts the hybrid tool approach from the ADK design for Ollama's function
calling format. The `ollama` library auto-converts Python functions with type
annotations and Google-style docstrings into JSON tool schemas.

```python
"""Tool registry for Ollama backend.

Ollama auto-converts Python functions with type annotations and
Google-style docstrings into JSON tool schemas. We expose the
same MatomoAPI/MetabaseAPI methods as the ADK design, plus
code execution and file reading tools.
"""

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from lib.query import (
    execute_matomo_query,
    execute_metabase_query,
    CallerType,
)


# ============ MATOMO TOOLS ============

def matomo_get_visits(
    site_id: int,
    period: str,
    date: str,
    segment: Optional[str] = None,
) -> str:
    """Get visit summary for a Matomo site.

    Args:
        site_id: Matomo site ID (e.g. 117 for Emplois)
        period: Time period - day, week, month, or range
        date: Date string (YYYY-MM-DD) or range (YYYY-MM-DD,YYYY-MM-DD)
        segment: Optional Matomo segment filter

    Returns:
        JSON string with visit metrics (nb_visits, nb_uniq_visitors, etc.)
    """
    params = {"idSite": site_id, "period": period, "date": date}
    if segment:
        params["segment"] = segment
    result = execute_matomo_query(
        instance="inclusion",
        caller=CallerType.AGENT,
        method="VisitsSummary.get",
        params=params,
    )
    if result.success:
        return str(result.data)
    return f"Error: {result.error}"

# ... (similar wrappers for other Matomo methods)


# ============ METABASE TOOLS ============

def metabase_execute_sql(
    sql: str,
    instance: str = "stats",
    database_id: int = 2,
) -> str:
    """Execute a SQL query on Metabase.

    Args:
        sql: The SQL query to execute
        instance: Metabase instance name (stats, datalake, dora)
        database_id: Database ID within the instance

    Returns:
        Query results as formatted string with columns and rows
    """
    result = execute_metabase_query(
        instance=instance,
        caller=CallerType.AGENT,
        sql=sql,
        database_id=database_id,
    )
    if result.success:
        return str(result.data)
    return f"Error: {result.error}"

# ... (similar wrappers for other Metabase methods)


# ============ CODE EXECUTION ============

def execute_python(code: str, timeout: int = 60) -> str:
    """Execute Python code for advanced queries.

    Use for multi-step analysis, data transformation, or queries
    that combine multiple API calls with custom logic.

    The code has access to the full Matometa environment:
        from lib.query import execute_matomo_query, execute_metabase_query

    Args:
        code: Python source code to execute
        timeout: Maximum execution time in seconds

    Returns:
        Script output (stdout + stderr)
    """
    # ... (subprocess execution, same as ADK design)


# ============ FILE TOOLS ============

def read_knowledge_file(path: str) -> str:
    """Read a file from the knowledge base.

    Args:
        path: Path relative to project root (e.g. knowledge/sites/emplois.md)

    Returns:
        File contents as string
    """
    # ... (safe file reading)


def list_knowledge_files(directory: str = "knowledge") -> str:
    """List files in the knowledge base.

    Args:
        directory: Directory relative to project root

    Returns:
        List of file paths
    """
    # ...


# ============ REGISTRY ============

def get_all_tools() -> list:
    """Get all tool functions for Ollama.

    Returns a list of Python functions that ollama will auto-convert
    to tool schemas via introspection.
    """
    return [
        matomo_get_visits,
        # matomo_get_pages,
        # matomo_get_events,
        # matomo_get_dimensions,
        # matomo_get_referrers,
        # matomo_raw_request,
        metabase_execute_sql,
        # metabase_execute_card,
        # metabase_search_cards,
        execute_python,
        read_knowledge_file,
        list_knowledge_files,
    ]
```

### Step 4: Create Ollama backend implementation

**File:** `web/agents/ollama.py` (new file)

```python
"""Ollama backend - uses ollama Python library with local/remote Ollama server."""

import asyncio
import json
import logging
import os
from typing import AsyncIterator, Optional

import ollama as ollama_lib
from ollama import AsyncClient, ChatResponse

from .. import config
from .base import AgentBackend, AgentMessage
from .ollama_tools import get_all_tools

logger = logging.getLogger(__name__)

# Configurable limits
MAX_TOOL_ROUNDS = int(os.getenv("OLLAMA_MAX_TOOL_ROUNDS", "20"))
MAX_HISTORY_CHARS = 50000

# System prompt preamble for Ollama-specific tool guidance
OLLAMA_PREAMBLE = """You are an AI agent with access to tools. When you need data,
call the appropriate tool function. You can make multiple tool calls in sequence.

Available tools are provided in the function definitions. Key tools:
- matomo_get_visits: Get visit statistics from Matomo analytics
- metabase_execute_sql: Run SQL queries on Metabase databases
- execute_python: Run Python scripts for complex analysis
- read_knowledge_file: Read documentation and knowledge base files
- list_knowledge_files: List available knowledge files

Always read relevant knowledge files before querying data sources.
"""


class OllamaBackend(AgentBackend):
    """Agent backend using Ollama with open-source models.

    Implements a self-managed agent loop:
    1. Send message with tools to Ollama
    2. If response contains tool_calls, execute them
    3. Append tool results to messages, repeat from 1
    4. When no more tool_calls, yield final response
    """

    def __init__(self):
        self._running: set[str] = set()
        self._cancelled: set[str] = set()
        self._model = os.getenv("OLLAMA_MODEL", "qwen3:32b")
        self._think = os.getenv("OLLAMA_THINK", "false").lower() == "true"
        self._num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))

    async def send_message(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentMessage]:
        """Send message via Ollama and yield streaming responses."""
        self._running.add(conversation_id)
        self._cancelled.discard(conversation_id)

        try:
            # Build system prompt
            system_prompt = self._build_system_prompt()

            # Build message history
            messages = self._build_messages(system_prompt, message, history)

            # Get tools
            tools = get_all_tools()
            available_functions = {f.__name__: f for f in tools}

            # Yield system init event
            yield AgentMessage(
                type="system",
                content="init",
                raw={"subtype": "init", "model": self._model},
            )

            # Agent loop
            for round_num in range(MAX_TOOL_ROUNDS):
                if conversation_id in self._cancelled:
                    yield AgentMessage(type="system", content="Cancelled")
                    return

                # Call Ollama with streaming
                client = AsyncClient()

                # Accumulate streamed response
                content_parts = []
                thinking_parts = []
                tool_calls = []

                async for chunk in await client.chat(
                    model=self._model,
                    messages=messages,
                    tools=tools,
                    stream=True,
                    think=self._think,
                    options={"num_ctx": self._num_ctx},
                ):
                    if conversation_id in self._cancelled:
                        yield AgentMessage(type="system", content="Cancelled")
                        return

                    # Stream thinking content (optional debug)
                    if hasattr(chunk.message, 'thinking') and chunk.message.thinking:
                        thinking_parts.append(chunk.message.thinking)

                    # Stream text content
                    if chunk.message.content:
                        content_parts.append(chunk.message.content)
                        yield AgentMessage(
                            type="assistant",
                            content=chunk.message.content,
                            raw={"streaming": True, "round": round_num},
                        )

                    # Collect tool calls
                    if chunk.message.tool_calls:
                        tool_calls.extend(chunk.message.tool_calls)

                # Build assistant message for history
                full_content = "".join(content_parts)
                assistant_msg = {
                    "role": "assistant",
                    "content": full_content,
                }
                if tool_calls:
                    assistant_msg["tool_calls"] = [
                        {
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            }
                        }
                        for tc in tool_calls
                    ]
                if thinking_parts:
                    assistant_msg["thinking"] = "".join(thinking_parts)
                messages.append(assistant_msg)

                # If no tool calls, we're done
                if not tool_calls:
                    break

                # Execute tool calls
                for tc in tool_calls:
                    func_name = tc.function.name
                    func_args = tc.function.arguments

                    # Yield tool_use event
                    yield AgentMessage(
                        type="tool_use",
                        content={"tool": func_name, "input": func_args},
                        raw={"round": round_num},
                    )

                    # Execute
                    func = available_functions.get(func_name)
                    if func:
                        try:
                            result = func(**func_args)
                        except Exception as e:
                            result = f"Error: {type(e).__name__}: {e}"
                    else:
                        result = f"Error: Unknown tool '{func_name}'"

                    # Yield tool_result event
                    yield AgentMessage(
                        type="tool_result",
                        content={"tool": func_name, "output": str(result)},
                        raw={"round": round_num},
                    )

                    # Append to messages for next round
                    messages.append({
                        "role": "tool",
                        "tool_name": func_name,
                        "content": str(result),
                    })

                # Clear tool_calls for next round
                tool_calls = []

            else:
                # Hit max rounds
                yield AgentMessage(
                    type="system",
                    content=f"Reached maximum tool rounds ({MAX_TOOL_ROUNDS})",
                )

            # Final system event with usage info
            yield AgentMessage(
                type="system",
                content="Completed: done",
                raw={
                    "result": True,
                    "model": self._model,
                    "rounds": round_num + 1,
                },
            )

        except Exception as e:
            logger.error(f"Ollama error: {e}", exc_info=True)
            yield AgentMessage(
                type="error",
                content=str(e),
                raw={"error": str(e), "type": type(e).__name__},
            )

        finally:
            self._running.discard(conversation_id)
            self._cancelled.discard(conversation_id)

    def _build_system_prompt(self) -> str:
        """Build system prompt from AGENTS.md with Ollama preamble."""
        agents_md_path = config.BASE_DIR / "AGENTS.md"
        agents_content = ""
        if agents_md_path.exists():
            agents_content = agents_md_path.read_text()

        from datetime import date
        today = date.today().strftime("%A %d %B %Y")

        return (
            f"Aujourd'hui, nous sommes le {today}.\n\n"
            f"{OLLAMA_PREAMBLE}\n\n"
            f"{agents_content}"
        )

    def _build_messages(
        self,
        system_prompt: str,
        message: str,
        history: list[dict],
    ) -> list[dict]:
        """Build Ollama message list from conversation history."""
        messages = [{"role": "system", "content": system_prompt}]

        # Include history (truncated to fit context window)
        total_chars = 0
        for msg in history:
            content = msg.get("content", "")
            if total_chars + len(content) > MAX_HISTORY_CHARS:
                break
            role = msg.get("role", "user")
            if role in ("user", "assistant"):
                messages.append({"role": role, "content": content})
                total_chars += len(content)

        # Current message
        messages.append({"role": "user", "content": message})
        return messages

    async def cancel(self, conversation_id: str) -> bool:
        """Cancel a running conversation."""
        if conversation_id in self._running:
            self._cancelled.add(conversation_id)
            return True
        return False

    def is_running(self, conversation_id: str) -> bool:
        """Check if a conversation is currently running."""
        return conversation_id in self._running
```

### Step 5: Register Ollama backend in factory

**File:** `web/agents/__init__.py`

```python
from .cli import CLIBackend
from .sdk import SDKBackend

__all__ = ["AgentBackend", "AgentMessage", "CLIBackend", "SDKBackend", "get_agent"]


def get_agent() -> AgentBackend:
    """Get the configured agent backend."""
    from .. import config

    if config.AGENT_BACKEND == "sdk":
        return SDKBackend()
    elif config.AGENT_BACKEND == "ollama":
        from .ollama import OllamaBackend
        return OllamaBackend()
    else:
        return CLIBackend()
```

### Step 6: Add Ollama config constants

**File:** `web/config.py`

Add:
```python
# Ollama settings
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:32b")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_AVAILABLE = True  # Always available (no API key needed)
```

---

## Event Mapping

Ollama responses map to `AgentMessage` types as follows:

| Ollama Response | AgentMessage Type | Notes |
|-----------------|-------------------|-------|
| `chunk.message.content` | `assistant` | Streamed token-by-token |
| `chunk.message.tool_calls` | `tool_use` | Emitted after stream completes |
| Tool execution result | `tool_result` | We execute and emit |
| `chunk.message.thinking` | `system` (optional) | Chain-of-thought from Qwen3/DeepSeek |
| Agent init | `system` | Emitted at start with model info |
| Agent complete | `system` | Emitted at end with round count |
| Exception | `error` | Caught and emitted |

---

## Key Differences from CLI/SDK Backends

| Aspect | CLI/SDK | Ollama |
|--------|---------|--------|
| Agent loop | Managed by Claude | Self-managed `while` loop |
| Tool execution | Claude runs tools internally | We execute Python functions directly |
| Session resumption | Via `--resume` / `options.resume` | Via message history replay |
| Streaming | Token-level via JSON events | Token-level via async generator |
| System prompt | AGENTS.md as-is | AGENTS.md + tool preamble |
| Token usage | Reported by Claude API | Not reported by Ollama (future: via response metadata) |
| Cost | Per-token API pricing | Infrastructure cost only |

---

## Model Recommendations

Based on community benchmarks for tool calling reliability:

| Model | Size | VRAM Needed | Tool Calling | Notes |
|-------|------|-------------|-------------|-------|
| **qwen3:32b** | 32B | 24-32 GB (q4) | Excellent | Best price/performance for agents |
| **deepseek-r1:32b** | 32B | 24-32 GB (q4) | Excellent | Strong reasoning, good with SQL |
| **llama3.3:70b** | 70B | 48+ GB (q4) | Very good | Meta's latest, broad capabilities |
| **qwen3:14b** | 14B | 12-16 GB (q4) | Good | Viable on consumer GPUs |
| **mistral:7b** | 7B | 8 GB | Basic | May struggle with complex tool chains |

**Important**: Models under 14B parameters tend to hallucinate tool calls or
forget parameters in complex multi-step scenarios. For production use, 32B+
is recommended.

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `requirements.txt` | Add `ollama>=0.6.1` |
| `.env.example` | Add `OLLAMA_HOST`, `OLLAMA_MODEL`, `OLLAMA_NUM_CTX`, `OLLAMA_THINK` |
| `docker-compose.yml` | Add Ollama env vars to environment section |
| `web/agents/ollama.py` | **Create** — main Ollama backend class |
| `web/agents/ollama_tools.py` | **Create** — tool registry (shared structure with ADK) |
| `web/agents/__init__.py` | Register Ollama backend in `get_agent()` |
| `web/config.py` | Add `OLLAMA_MODEL`, `OLLAMA_HOST`, `OLLAMA_AVAILABLE` |

---

## Verification Plan

### 1. Prerequisites

```bash
# Install Ollama
curl -fsSL https://ollama.com/install.sh | sh

# Pull a model with tool calling support
ollama pull qwen3:32b
# or for testing on smaller hardware:
ollama pull qwen3:14b
```

### 2. Local test without Docker

```bash
# Set up
export AGENT_BACKEND=ollama
export OLLAMA_MODEL=qwen3:32b

# Run web server
.venv/bin/python -m web.app

# Test in browser
# Query: "Combien de visites sur Emplois en decembre 2024?"
```

### 3. Verify streaming

- Open browser dev tools → Network → EventSource
- Check events flow: `system` → `assistant` → `tool_use` → `tool_result` → `assistant`
- Verify text streams incrementally (not all at once)

### 4. Verify tool calls

- Check `matomo_get_visits` is called with correct args
- Check `execute_python` works for advanced queries
- Check `read_knowledge_file` can read knowledge base

### 5. Docker test

```bash
# Ollama runs on host, Matometa in container
AGENT_BACKEND=ollama docker compose up
```

### 6. Multi-round test

Ask a question that requires multiple tool calls:
> "Compare le trafic d'Emplois et du Marche en janvier 2025. Lis d'abord les
> fiches de connaissance des deux sites."

Expected: model reads knowledge files, then queries Matomo for both sites,
then writes a comparison.

---

## Risks and Mitigations

### Tool calling reliability

**Risk**: Smaller models may hallucinate tool names, forget required parameters,
or enter infinite tool-calling loops.

**Mitigations**:
- Default to 32B+ model
- `MAX_TOOL_ROUNDS` cap (default: 20)
- Clear function docstrings with explicit parameter documentation
- Tool preamble in system prompt listing available tools

### Context window limits

**Risk**: Long conversations + system prompt + tool results may exceed context.

**Mitigations**:
- `MAX_HISTORY_CHARS` truncation (default: 50,000)
- Configurable `OLLAMA_NUM_CTX` (default: 32,768)
- Tool results truncated if too long

### Streaming + tool calls buffering

**Risk**: Some Ollama versions buffer responses during tool call resolution
rather than streaming incrementally.

**Mitigation**: Acceptable for now — text streams normally between tool rounds.
The user sees tool_use/tool_result events during the buffered phase, keeping
the UI responsive.

### No token usage reporting

**Risk**: `accumulate_usage()` in the streaming handler expects usage data.

**Mitigation**: Ollama doesn't report token counts in the same way. We emit
the `system` completion event without usage data. The streaming handler already
handles missing usage gracefully (checks `if event.raw.get("usage")`).

---

## Future Enhancements

1. **Token counting**: Ollama responses include `eval_count` and
   `prompt_eval_count` — map these to `input_tokens`/`output_tokens`
2. **Model health check**: Add `/api/health` endpoint that checks Ollama
   connectivity and model availability
3. **Shared tool registry**: Extract common tool definitions into a shared
   module used by both ADK and Ollama backends
4. **OpenAI compatibility mode**: Alternative to native `ollama` library,
   use Ollama's `/v1/chat/completions` endpoint via the `openai` library
   for providers that expose an OpenAI-compatible API (vLLM, LM Studio, etc.)
5. **Parallel tool calls**: Execute multiple tool calls concurrently when the
   model requests them in the same response
