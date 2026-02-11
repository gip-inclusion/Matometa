# Plan: Add Open-Weight Model Backend (via Ollama)

## Goal

Add a self-hosted, open-weight model backend as a fourth option alongside Claude
CLI, SDK, and (planned) ADK backends, enabling models like Qwen3, Llama 3.3,
DeepSeek, and Mistral to power the Matometa agent with the same web UI and tool
ecosystem — with no external API calls for inference.

## Why Self-Hosted Open-Weight Models

- **Data sovereignty**: Inference runs on infrastructure we control. No data
  leaves the network.
- **No API keys**: No per-token cost, no rate limits, no vendor dependency for
  the inference layer.
- **Model choice**: Swap models freely — try Qwen3 for tool calling, DeepSeek
  for reasoning, Llama for general use — without changing code.
- **Development & testing**: Run a lightweight model locally for rapid iteration
  without burning API credits.

## Serving Infrastructure: Landscape

The open-weight model ecosystem has matured significantly. All major serving
tools now expose an **OpenAI-compatible API** (`/v1/chat/completions`), which is
the de facto standard. They differ in target use case and operational complexity.

### Comparison

| Server | Best For | Tool Calling | Streaming | Setup | GPU Req | Notes |
|--------|----------|-------------|-----------|-------|---------|-------|
| **[Ollama](https://ollama.com)** | Dev, small teams, single-GPU | Yes (native + `/v1/`) | Yes | `curl \| sh` | Optional | Go binary wrapping llama.cpp. One-command install, model management built in. |
| **[vLLM](https://docs.vllm.ai)** | Production, high throughput | Yes (`--enable-auto-tool-choice`) | Yes | pip + CLI | Required (NVIDIA) | PagedAttention, continuous batching, 2-4x throughput vs others at scale. Steeper setup. |
| **[llama.cpp server](https://github.com/ggml-org/llama.cpp)** | Edge, CPU-only, minimal deps | Yes (OpenAI-compat + Anthropic-compat) | Yes | Build from source or download binary | Optional | Zero dependencies, runs on anything. Now supports Anthropic Messages API too. |
| **[LocalAI](https://localai.io)** | Universal API gateway | Yes (OpenAI functions + MCP) | Yes | Docker | Optional | Drop-in OpenAI replacement, routes to multiple backends, native MCP support. |
| **[LM Studio](https://lmstudio.ai)** | Prototyping, GUI exploration | Yes (basic) | Yes | Desktop app | Optional | Nice GUI, but no streaming tool calls or parallel invocation. Desktop-only. |
| **[SGLang](https://github.com/sgl-project/sglang)** | Multi-turn, KV cache reuse | Partial (built-in tools only) | Yes | pip + CLI | Required (NVIDIA) | Faster than vLLM for multi-turn conversations (RadixAttention). User-defined tool calling still maturing. |

### Key Observations

1. **All expose `/v1/chat/completions`** — any backend we write against one
   server's OpenAI-compatible API would work with the others.
2. **Tool calling maturity varies** — Ollama and vLLM have the most mature
   function calling. SGLang and LM Studio are catching up.
3. **Operational profiles differ** — Ollama is "install and run"; vLLM needs
   GPU orchestration but delivers production throughput; llama.cpp runs anywhere.

### Recommended Path

**Start with Ollama, design for portability.**

- Ollama is the simplest to get running and has the most complete tool calling
  support for a single-server setup.
- The agent loop and tool execution code we write is server-agnostic — it
  consumes chat completions and produces tool results, regardless of which
  server runs the model.
- If throughput or scaling needs grow, switching to vLLM or llama.cpp server
  requires only changing the server URL and possibly the model name format.
  The backend code stays the same.

A future enhancement (see "Future Enhancements") could add an `openai`-library
variant that targets the `/v1/` endpoint directly, making the backend work with
*any* OpenAI-compatible server without the `ollama` dependency. This is not
needed for v1 — the native `ollama` library gives us the best developer
experience for the initial implementation.

## Architecture Overview

```
AgentBackend (abstract base class)
├── CLIBackend   → spawns `claude` CLI process
├── SDKBackend   → uses claude-agent-sdk Python package
├── ADKBackend   → (planned) uses google-adk Python package
└── OllamaBackend → NEW: uses ollama Python package (self-hosted open-weight models)
```

All backends yield `AgentMessage` objects, streamed to the frontend via SSE.

## Library Choice: `ollama` (native Python client)

**Selected**: [`ollama`](https://github.com/ollama/ollama-python) v0.6.1+

**Alternatives considered:**

| Library | Pros | Cons |
|---------|------|------|
| **`ollama`** (native) | Direct async support, auto-schema from Python functions, best feature coverage, minimal deps | Tied to Ollama server; no built-in agent loop |
| `openai` (compat endpoint) | Works with any `/v1/`-compatible server (vLLM, llama.cpp, LocalAI), familiar API | Ollama's `/v1/` streaming tool calls still incomplete (late 2025); manual JSON schema for tools |
| `litellm` | Unified API across 100+ providers, could share code with cloud backends | Known bugs with Ollama streaming+tools+async (2025), heavy dependency tree, extra abstraction |

The native `ollama` library is the best fit for v1 because:
1. It auto-generates tool schemas from Python function signatures + docstrings
   (same approach as ADK's `FunctionTool`) — no manual JSON schema authoring
2. `AsyncClient` supports `chat()` with `tools=` and `stream=True`
3. Minimal dependency footprint (one package)
4. Most direct path — no translation layers
5. Ollama is the most likely first server users will run

**Portability note**: The agent loop, tool registry, and event mapping are all
server-agnostic. If we later add an `openai`-library variant, 90% of the code
(everything except the `client.chat()` call and response parsing) is reusable.

## Implementation Status (`ollama_implementation` branch)

The `ollama_implementation` branch has a working prototype that **diverges from
this plan in key ways**. This section documents what was actually built, how it
differs, and what to do next.

### What was built

| Component | Plan | Actual |
|-----------|------|--------|
| **HTTP client** | `ollama` Python library (`AsyncClient`) | Raw `httpx` against `/api/chat` |
| **Tool calling** | Native `tools=` param → structured `tool_calls` in response | Text-based JSON protocol: model outputs `{"tool": "Read", "input": {...}}` |
| **Tool set** | Domain-specific functions (`matomo_get_visits`, `metabase_execute_sql`, etc.) auto-converted to schemas | Generic tools (Read, Write, Edit, Glob, Grep, Bash, Skill) — same toolset as Claude backends |
| **Tool parsing** | Ollama parses tool calls from structured response | `json.loads()` on raw model output text |
| **Agent loop** | `while tool_calls: execute → append → repeat` | Same loop structure, but detects tools by parsing text, not structured response |
| **LLM helper** | Not in plan | `web/llm.py` — backend-agnostic module for short prompts (titles, tags). Replaces hardcoded Anthropic calls in conversations.py |
| **Streaming** | Via `ollama` async generator | Via `httpx` streaming + `aiter_lines()` with smart buffering (suppresses streaming for JSON/code blocks) |
| **Config** | 3 env vars (`OLLAMA_MODEL`, `OLLAMA_HOST`, `OLLAMA_NUM_CTX`) | 10+ env vars (model, base URL, timeout, stream chunk size, max history, max tool steps, temperature, num_ctx, separate title/tag models) |
| **Thinking mode** | `think=True` param via ollama library | Not implemented |

### Key files on the branch

```
web/agents/ollama.py       # 240 lines — OllamaBackend class, httpx streaming
web/agents/ollama_tools.py # 260 lines — text-based tool protocol + executors
web/llm.py                 # 144 lines — backend-agnostic generate_text()
web/config.py              # Expanded with OLLAMA_* settings
web/agents/__init__.py     # Updated get_agent() factory
web/routes/conversations.py # Refactored to use llm.generate_text()
tests/test_llm_ollama.py   # httpx mock test for llm.py
tests/test_ollama_tools.py # parse_tool_call unit test
```

### Analysis: text-based tools vs native tool calling

The actual implementation chose a **text-based tool protocol** instead of
Ollama's native `tools=` parameter. This is a deliberate tradeoff:

**Advantages of text-based approach (what was built):**
- No `ollama` library dependency — pure httpx, works against any HTTP chat API
- Same generic toolset as Claude backends (Read/Write/Bash/etc.) — the model
  operates more like Claude Code, navigating files and running commands
- Simpler dependency tree (httpx is already a transitive dep)
- Naturally portable to vLLM, llama.cpp, or any `/api/chat`-compatible server

**Advantages of native tool calling (what was planned):**
- Structured tool_calls — no risk of JSON parse failures on model output
- Domain-specific tools (matomo_get_visits) give the model clearer semantics
- Ollama handles tool schema generation from function signatures
- Works with models that support structured output but struggle with free-form
  JSON generation
- `think=True` for reasoning models is easy to add

**Verdict:** The text-based approach is a reasonable v1 — it works and it's
portable. But tool calling reliability will suffer with smaller models (< 14B)
that can't reliably emit valid JSON. The native tool calling path should be
the v2 upgrade, especially once we want to use domain-specific tools.

### Analysis: `web/llm.py` (not in plan — good addition)

The branch adds `web/llm.py`, a backend-agnostic helper for short text
generation (titles, tags). This is a genuine improvement:
- Replaces 3 separate hardcoded Anthropic SDK calls in `conversations.py`
- Routes through the configured backend (ollama, sdk, or cli)
- Supports per-task model overrides (`OLLAMA_TITLE_MODEL`, `OLLAMA_TAG_MODEL`)
- The `conversations.py` diff deletes ~90 lines of duplicated code

This wasn't in the plan but should be kept. It belongs in the implementation.

### What's missing vs the plan

1. **No `ollama` library usage** — the plan centered on `ollama>=0.6.1` for
   native async tool calling. The implementation uses raw httpx instead.
2. **No domain-specific tools** — no `matomo_get_visits()`, no
   `metabase_execute_sql()`. The model uses generic Bash/Read/Skill tools.
3. **No thinking mode** — `think=True` for Qwen3/DeepSeek-R1 not implemented.
4. **No token counting** — `eval_count`/`prompt_eval_count` from Ollama
   responses are not captured.
5. **Minimal tests** — 2 unit tests. No integration tests for the agent loop
   or streaming.

---

## Design Decisions (updated to reflect implementation)

### 1. Agent loop: Self-managed

Same as planned. The agent loop is a `while` loop that sends messages, checks
for tool calls in the response, executes them, appends results, and repeats.

The implementation caps at `OLLAMA_TOOL_MAX_STEPS` (default: 6) rounds. The
plan proposed 20 — the implementation's lower default is more conservative,
which is appropriate for a text-based tool protocol where runaway loops are
more likely.

### 2. Tool approach: Generic toolset via text protocol

**Diverged from plan.** Instead of domain-specific function tools with
auto-schema, the implementation uses a text-based protocol where the system
prompt tells the model to emit JSON objects for tool calls:

```
{"tool": "Read", "input": {"file_path": "knowledge/sites/emplois.md"}}
{"tool": "Bash", "input": {"command": "python3 scripts/query_matomo.py ..."}}
{"tool": "Skill", "input": {"skill": "matomo_query"}}
```

This gives the model the same capabilities as Claude backends but through
string-based tool dispatch. Parsing relies on `json.loads()` of the full
response text — fragile but functional.

### 3. Session management: Message history (as planned)

Implemented as designed. Full message history replay, truncated at
`OLLAMA_MAX_HISTORY_CHARS` (50,000 chars). No session ID. Stateless on the
Ollama side.

### 4. Model configuration (expanded)

More extensive than planned:

```
OLLAMA_BASE_URL          (http://ollama:11434)
OLLAMA_MODEL             (qwen3-coder-next)
OLLAMA_TITLE_MODEL       (defaults to OLLAMA_MODEL)
OLLAMA_TAG_MODEL         (defaults to OLLAMA_MODEL)
OLLAMA_REQUEST_TIMEOUT   (120s)
OLLAMA_STREAM            (true)
OLLAMA_STREAM_CHUNK_SIZE (200 chars)
OLLAMA_MAX_HISTORY_CHARS (50000)
OLLAMA_TOOL_MAX_STEPS    (6)
OLLAMA_TEMPERATURE       (0.2)
OLLAMA_NUM_CTX           (0 = model default)
```

The separate title/tag model vars (`OLLAMA_TITLE_MODEL`, `OLLAMA_TAG_MODEL`)
are a nice touch — they allow using a smaller/faster model for housekeeping
tasks while running a larger model for agent conversations.

### 5. System prompt: AGENTS.md + tool protocol

As planned, AGENTS.md is the base. The implementation prepends a date and
appends the tool protocol instructions (in French, matching the project
language). No separate preamble about domain tools — the generic tool protocol
replaces it.

### 6. Streaming: Smart buffering

The implementation adds intelligent stream buffering that wasn't in the plan:
- Detects if the response starts with `{` or `` ` `` (JSON or code fence)
- If so, suppresses streaming (buffers the full response) — avoids streaming
  a raw JSON tool call to the frontend character by character
- If it's regular text, streams in `OLLAMA_STREAM_CHUNK_SIZE` chunks
- This is a practical improvement that handles the text-based tool protocol
  cleanly

### 7. Thinking mode: Not implemented

Deferred. Could be added later by passing `think=True` in the Ollama payload
and parsing `message.thinking` from the response.

---

## Next Steps (informed by `ollama_implementation` branch)

The branch has a working prototype. Here's what to do next, in priority order:

### Step 1: Merge the branch as-is (v1 = text-based tools)

The current implementation works. Merge it to get the Ollama backend live.
Key files to review:
- `web/agents/ollama.py` — main backend (httpx-based, text tool protocol)
- `web/agents/ollama_tools.py` — tool protocol + sandboxed executors
- `web/llm.py` — backend-agnostic short-prompt helper
- `web/config.py` — OLLAMA_* settings
- `web/routes/conversations.py` — refactored to use `llm.generate_text()`

### Step 2: Add native tool calling mode (v2)

Add Ollama's native `tools=` parameter as an opt-in mode alongside the
text-based protocol. This improves reliability with models that support
structured tool calling (Qwen3, Llama 3.3, Mistral).

Two approaches, not mutually exclusive:

**Option A: `ollama` library with native tools**
```python
import ollama
response = await ollama.AsyncClient().chat(
    model=model, messages=messages, tools=get_all_tools(), stream=True
)
# tools= accepts Python functions; ollama auto-generates JSON schemas
```

**Option B: Raw httpx with `tools` in payload**
```python
payload = {
    "model": model,
    "messages": messages,
    "tools": [{"type": "function", "function": {...schema...}}],
    "stream": True,
}
# Works with any /api/chat-compatible server
```

Either way, the domain-specific tools from the original plan
(`matomo_get_visits`, `metabase_execute_sql`, etc.) become the tool registry.
The agent loop checks `response.message.tool_calls` instead of parsing text.

Controlled by env var: `OLLAMA_TOOL_MODE=native` (vs default `text`).

### Step 3: Add thinking/reasoning support

For Qwen3 and DeepSeek-R1: pass `think=True` in the Ollama payload, capture
`message.thinking` content, and optionally stream it to the UI as a collapsible
reasoning trace. Controlled by `OLLAMA_THINK=true`.

### Step 4: Add token counting

Ollama responses include `eval_count` (output tokens) and `prompt_eval_count`
(input tokens). Capture these from the final streaming chunk (`done: true`)
and emit them in the system completion event for usage tracking.

### Step 5: Integration tests

Expand test coverage beyond the 2 unit tests:
- Mock the full agent loop (multi-round tool calling)
- Test streaming with smart buffering
- Test history truncation edge cases
- Test cancellation mid-stream

---

## Event Mapping (as implemented)

| Source | AgentMessage Type | Notes |
|--------|-------------------|-------|
| Streamed text (non-JSON) | `assistant` with `raw.append=True` | Chunked via `OLLAMA_STREAM_CHUNK_SIZE` |
| Full non-streamed response | `assistant` | When streaming disabled or response is JSON/code |
| Parsed JSON tool call | `tool_use` | `{"tool": name, "input": args}` |
| Tool execution result | `tool_result` | `{"tool": name, "output": text}` |
| Cancellation | `system` | `{"cancelled": True}` |
| Max steps exceeded | `error` | `{"tool_steps": N}` |
| Exception | `error` | Caught and emitted |

---

## Key Differences from CLI/SDK Backends

| Aspect | CLI/SDK | Ollama (current) |
|--------|---------|------------------|
| Agent loop | Managed by Claude | Self-managed `while` loop |
| Tool dispatch | Claude runs tools internally | Text-based JSON protocol parsed by us |
| Tool set | Skills/MCP tools | Read/Write/Edit/Glob/Grep/Bash/Skill |
| Session resumption | Via `--resume` / `options.resume` | Via message history replay |
| Streaming | Token-level via JSON events | httpx `aiter_lines()` with smart buffering |
| System prompt | AGENTS.md as-is | AGENTS.md + tool protocol instructions |
| Short prompts | Hardcoded Anthropic SDK calls | `llm.generate_text()` (backend-agnostic) |
| Token usage | Reported by Claude API | Not captured yet |
| Cost | Per-token API pricing | Infrastructure cost only |
| Cancellation | Kill CLI process / SDK cancel | `asyncio.Event` flag checked each iteration |

---

## Model Recommendations

Based on community benchmarks for tool calling reliability:

| Model | Size | VRAM Needed | Tool Calling | Notes |
|-------|------|-------------|-------------|-------|
| **qwen3:32b** | 32B | 24-32 GB (q4) | Excellent | Best price/performance for agents |
| **deepseek-r1:32b** | 32B | 24-32 GB (q4) | Excellent | Strong reasoning, good with SQL |
| **llama3.3:70b** | 70B | 48+ GB (q4) | Very good | Meta's latest, broad capabilities |
| **qwen3:14b** | 14B | 12-16 GB (q4) | Good | Viable on consumer GPUs |
| **mistral:7b** | 7B | 8 GB | Basic | May struggle with text-based tool protocol |

**Important**: The text-based tool protocol (model emits JSON) is more
demanding than native tool calling. Models under 14B often fail to emit valid
JSON consistently. For production with text-based tools, 32B+ is recommended.
With native tool calling (v2), smaller models may perform better.

The branch defaults to `qwen3-coder-next` — verify this model exists in the
Ollama registry or update the default.

---

## Risks and Mitigations (updated for implementation)

### Tool calling reliability (elevated for text-based protocol)

**Risk**: The text-based tool protocol relies on the model outputting
syntactically valid JSON. Smaller models may emit malformed JSON, hallucinate
tool names, mix prose with JSON, or enter tool-calling loops.

**Mitigations (in place)**:
- `OLLAMA_TOOL_MAX_STEPS` cap (default: 6 — conservative)
- Smart stream buffering: detects JSON-starting responses and suppresses
  streaming to avoid partial JSON in the UI
- `_strip_code_fence()` handles models that wrap JSON in ```code blocks```
- Allowlisted tool names — unknown tools return an error message, not a crash

**Future mitigation**: Native tool calling (v2) eliminates JSON parsing risk
entirely. The model returns structured `tool_calls` objects.

### Bash tool security

**Risk**: The Bash tool executor runs shell commands from model output. Even
with allowlist filtering, a sufficiently creative model could craft a command
that matches the glob pattern but does something unintended.

**Mitigations (in place)**:
- `_bash_allowed()` checks commands against `ALLOWED_TOOLS` glob patterns
- Container-level sandboxing is the real security boundary
- Commands run with `subprocess.run(timeout=300)` — bounded execution

**Note**: The `_bash_allowed` implementation uses `fnmatch.fnmatch` on the full
command string. This is coarse — a pattern like `Bash(python:*)` matches any
command starting with `python`, which is very broad. This is acceptable because
the container is the trust boundary, but worth noting.

### Context window limits

**Risk**: Long conversations + system prompt + tool results may exceed context.

**Mitigations (in place)**:
- `OLLAMA_MAX_HISTORY_CHARS` truncation (default: 50,000)
- Configurable `OLLAMA_NUM_CTX` (default: 0 = model default)
- `_truncate()` caps tool output at 12,000 chars

### File system access scope

**Risk**: Read/Write/Edit tools could access files outside the project.

**Mitigations (in place)**:
- `_is_within()` checks paths against allowed roots (BASE_DIR, DATA_DIR, /tmp)
- `_resolve_path()` resolves symlinks before checking
- Write access is more restricted than Read (no ADDITIONAL_DIRS)

### No token usage reporting

**Risk**: Usage tracking expects token counts from the backend.

**Mitigation**: The implementation doesn't capture token counts. The streaming
handler in `conversations.py` already handles missing usage gracefully. Token
counting from Ollama responses (`eval_count`, `prompt_eval_count`) is a planned
future enhancement.

---

## Future Enhancements

1. **Native tool calling mode** (highest priority): Add `tools=` parameter
   support with domain-specific Python functions. Either via `ollama` library
   or raw JSON schemas in httpx payload. Controlled by `OLLAMA_TOOL_MODE`.
2. **OpenAI-compatible variant**: Since the current implementation already uses
   raw httpx against `/api/chat`, adapting it to `/v1/chat/completions` is
   straightforward. This would enable vLLM, llama.cpp, LocalAI, etc. with no
   code changes beyond URL and payload format.
3. **Token counting**: Capture `eval_count` and `prompt_eval_count` from
   Ollama's `done: true` chunk for usage tracking.
4. **Thinking mode**: `think=True` for Qwen3/DeepSeek-R1 reasoning traces.
5. **Model health check**: `/api/health` endpoint to verify Ollama connectivity
   and model availability before accepting conversations.
6. **Parallel tool calls**: Execute multiple tool calls concurrently via
   `asyncio.gather` when the model requests several in one turn.
7. **vLLM production deployment guide**: Docker Compose setup with vLLM for
   teams needing higher throughput than single-GPU Ollama.
