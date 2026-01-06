# SDK Backend Design

**Date:** 2026-01-06
**Status:** Draft
**Predecessor:** 2026-01-05-web-frontend-design.md

---

## Overview

Add a cloud-deployable backend using the Claude Agent SDK alongside the existing CLI backend. The web UI already supports backend swapping via `AGENT_BACKEND` environment variable.

### Current State

- CLI backend (`CLIBackend`) spawns `claude` CLI with `--output-format stream-json`
- Works locally, requires Claude Code CLI installed on server
- Abstract `AgentBackend` interface ready for SDK implementation
- Stub `SDKBackend` raises `NotImplementedError`

### Target State

- `SDKBackend` uses `claude-agent-sdk` Python package
- Same streaming interface (SSE events) as CLI backend
- Deployable to cloud without Claude Code CLI dependency
- Session persistence for multi-turn conversations

---

## Claude Agent SDK Key Concepts

The Agent SDK is the programmatic equivalent of Claude Code:

| Feature | CLI Backend | SDK Backend |
|---------|-------------|-------------|
| Runtime | Spawns `claude` CLI process | Uses `claude-agent-sdk` package |
| Tool loop | CLI handles internally | SDK handles automatically |
| Streaming | Parse JSON lines from stdout | Async iterator over messages |
| Session | `--resume` flag | `session_id` parameter |
| Tools | All Claude Code tools | Same tools, configurable |

### SDK Installation

```bash
# 1. Install Claude Code CLI as runtime component
npm install -g @anthropic-ai/claude-code

# 2. Install the SDK
pip install claude-agent-sdk
```

**Architecture:** The SDK spawns Claude Code as a subprocess and controls it programmatically. You never interact with the CLI directly - your code uses the SDK's Python API. The CLI handles API calls and tool execution internally.

### Two Usage Patterns

**`query()` — One-off tasks:**
```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(
    prompt="Analyze visitor trends",
    options=ClaudeAgentOptions(
        allowed_tools=["Read", "Bash", "Grep"],
        cwd="/path/to/matometa"
    )
):
    yield message
```

**`ClaudeSDKClient` — Multi-turn conversations:**
```python
from claude_agent_sdk import ClaudeSDKClient

async with ClaudeSDKClient() as client:
    await client.query("What's the traffic on Emplois?")
    async for message in client.receive_response():
        yield message

    # Follow-up with context preserved
    await client.query("Compare to last month")
    async for message in client.receive_response():
        yield message
```

---

## Implementation Plan

### 1. SDKBackend Class

```python
# web/agents/sdk.py
from typing import AsyncIterator, Optional
from claude_agent_sdk import query, ClaudeAgentOptions, ClaudeSDKClient

from .base import AgentBackend, AgentMessage


class SDKBackend(AgentBackend):
    """Agent backend using Claude Agent SDK."""

    def __init__(self):
        self._running: dict[str, ClaudeSDKClient] = {}
        self._sessions: dict[str, str] = {}  # conv_id -> session_id

    async def send_message(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        session_id: Optional[str] = None,
    ) -> AsyncIterator[AgentMessage]:
        """Send message via SDK and yield streaming responses."""

        # Build options
        options = ClaudeAgentOptions(
            allowed_tools=["Read", "Bash", "Grep", "Glob", "Write", "Edit"],
            cwd=str(config.BASE_DIR),
            system_prompt=self._load_system_prompt(),
        )

        # Resume session if available
        if session_id or conversation_id in self._sessions:
            options.resume = session_id or self._sessions[conversation_id]

        # Stream responses
        async for sdk_message in query(prompt=message, options=options):
            # Capture session ID from init message
            if hasattr(sdk_message, 'subtype') and sdk_message.subtype == 'init':
                self._sessions[conversation_id] = sdk_message.session_id

            # Normalize to AgentMessage
            yield self._normalize_message(sdk_message)

    def _normalize_message(self, sdk_message) -> AgentMessage:
        """Convert SDK message to our normalized format."""
        # Map SDK message types to our types
        if hasattr(sdk_message, 'type'):
            msg_type = sdk_message.type
        else:
            msg_type = "system"

        return AgentMessage(
            type=msg_type,
            content=getattr(sdk_message, 'content', str(sdk_message)),
            raw=sdk_message.__dict__ if hasattr(sdk_message, '__dict__') else {}
        )

    def _load_system_prompt(self) -> str:
        """Load AGENTS.md as system prompt."""
        agents_md = config.BASE_DIR / "AGENTS.md"
        if agents_md.exists():
            return agents_md.read_text()
        return ""

    async def cancel(self, conversation_id: str) -> bool:
        """Cancel running conversation."""
        if conversation_id in self._running:
            client = self._running.pop(conversation_id)
            # SDK may have cancel method
            return True
        return False

    def is_running(self, conversation_id: str) -> bool:
        """Check if conversation is running."""
        return conversation_id in self._running
```

### 2. Message Type Mapping

Map SDK message types to current SSE event types:

| SDK Message | SSE Event Type | Content |
|-------------|----------------|---------|
| `AssistantMessage` | `assistant` | Text content |
| `ToolUseBlock` | `tool_use` | Tool name + input |
| `ToolResultBlock` | `tool_result` | Tool output |
| `SystemMessage` | `system` | System info |
| `ErrorMessage` | `error` | Error details |

### 3. Configuration

```python
# web/config.py
AGENT_BACKEND = os.getenv("AGENT_BACKEND", "cli")  # "cli" or "sdk"

# SDK-specific settings
SDK_ALLOWED_TOOLS = [
    "Read", "Write", "Edit", "Bash", "Glob", "Grep"
]
SDK_MAX_TURNS = 50
SDK_PERMISSION_MODE = "acceptEdits"  # Auto-approve for web use
```

### 4. System Prompt Injection

For cloud deployment, inject context that CLI loads from filesystem:

```python
def build_system_prompt() -> str:
    """Build system prompt with Matometa context."""
    parts = []

    # Core agent instructions
    agents_md = config.BASE_DIR / "AGENTS.md"
    if agents_md.exists():
        parts.append(agents_md.read_text())

    # Site-specific context (optional, based on query)
    # Could be injected dynamically based on conversation

    return "\n\n---\n\n".join(parts)
```

---

## Deployment Considerations

### Local Development (CLI backend)
```bash
AGENT_BACKEND=cli .venv/bin/python -m web.app
```

### Cloud Deployment (SDK backend)

**Server requirements:**
- Node.js 18+
- Claude Code CLI: `npm install -g @anthropic-ai/claude-code`
- Python 3.10+
- `pip install claude-agent-sdk`

```bash
AGENT_BACKEND=sdk ANTHROPIC_API_KEY=sk-... python -m web.app
```

**Docker example:**
```dockerfile
FROM python:3.11-slim
RUN apt-get update && apt-get install -y nodejs npm
RUN npm install -g @anthropic-ai/claude-code
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . /app
WORKDIR /app
CMD ["python", "-m", "web.app"]
```

### Security

1. **Tool restrictions:** Limit to safe tools in cloud
   ```python
   allowed_tools=["Read", "Grep", "Glob"]  # No Bash/Write in prod?
   ```

2. **Directory sandboxing:**
   ```python
   cwd="/app/matometa"
   # Only allow read from knowledge/, reports/
   ```

3. **Rate limiting:** SDK respects API limits, but add app-level limits

4. **Cost control:**
   ```python
   options = ClaudeAgentOptions(
       max_turns=20,
       max_budget_usd=5.0
   )
   ```

### Session Persistence

For cloud deployment, persist sessions to database:

```python
# Future: SQLite session storage
class SessionStore:
    def save(self, conv_id: str, session_id: str): ...
    def get(self, conv_id: str) -> Optional[str]: ...
    def delete(self, conv_id: str): ...
```

---

## Migration Path

### Phase 1: Basic SDK Backend
- Implement `SDKBackend` class
- Test with `AGENT_BACKEND=sdk`
- Verify SSE streaming works identically

### Phase 2: Session Persistence
- Add SQLite session storage
- Support conversation resumption across restarts

### Phase 3: Cloud Hardening
- Tool restrictions for production
- Rate limiting
- Cost monitoring
- Error handling improvements

### Phase 4: Feature Parity
- Ensure all CLI features work via SDK
- Add SDK-specific features (subagents, etc.)

---

## Open Questions

1. **Tool permissions:** Which tools should be enabled in cloud? Bash is powerful but risky.

2. **Session storage:** In-memory OK for MVP? When to add SQLite?

3. **Cost management:** Per-user budgets? Organization-wide limits?

4. **Container deployment:** Docker image with Node.js + Claude Code CLI + Python SDK?

---

## References

- Agent SDK docs: https://platform.claude.com/docs/en/agent-sdk/overview
- Current CLI backend: `web/agents/cli.py`
- Frontend design: `docs/plans/2026-01-05-web-frontend-design.md`
