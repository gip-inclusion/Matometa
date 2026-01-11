# Pub/Sub Streaming Architecture

**Date:** 2026-01-11
**Status:** Proposal
**Context:** Fix for duplicate agent responses revealed architectural issues in streaming

---

## Problem Statement

The current streaming architecture conflates two concerns:

1. **Subscribing to events** - "show me what's happening"
2. **Starting agent work** - "process the pending message"

This caused a bug where navigating away and back triggered duplicate agent responses. The immediate fix (checking if last message was answered) works, but the architecture remains fragile for:

- Multi-user collaboration (two users on same conversation)
- Multi-window scenarios (same user, two tabs)
- Network interruptions and reconnections

---

## Current Architecture

```
┌─────────┐     POST /messages      ┌─────────┐
│ Browser │ ──────────────────────► │  Flask  │  (stores message, returns)
└─────────┘                         └─────────┘
     │
     │        GET /stream
     └─────────────────────────────► ┌─────────┐
                                     │  Flask  │  (starts agent, streams SSE)
                                     └─────────┘
```

**Problems:**

| Issue | Impact |
|-------|--------|
| `/stream` starts agent if not running | Duplicate responses on reconnect |
| No subscriber tracking | Can't broadcast to multiple clients |
| Stream dies on navigation | User loses connection, must reconnect |
| One stream per request | No way to have multiple listeners |

---

## Proposed Architecture

```
┌─────────────┐   POST /messages   ┌─────────┐
│  Browser A  │ ─────────────────► │  Flask  │ ─► stores message
└─────────────┘                    └─────────┘    queues agent work
       │                                │
       │      GET /stream               │
       └────────────────────────────────┼──► ┌──────────────┐
                                        │    │  PubSub Hub  │
┌─────────────┐   GET /stream           │    │              │
│  Browser B  │ ────────────────────────┼──► │  subscribers │
└─────────────┘                         │    │  per conv_id │
                                        │    └──────────────┘
                                        │           │
                                   ┌────┴────┐      │
                                   │  Agent  │ ─────┘
                                   │  Runner │  broadcasts events
                                   └─────────┘
```

### Key Changes

1. **`POST /messages`** - Stores message AND triggers agent (if not running)
2. **`GET /stream`** - Subscribe only, never starts work
3. **PubSub Hub** - In-memory registry of subscribers per conversation
4. **Agent Runner** - Broadcasts events to all subscribers

---

## API Changes

### POST /api/conversations/{id}/messages

**Current:** Stores message, returns immediately
**Proposed:** Stores message, queues agent work if idle, returns status

```python
@bp.route("/<conv_id>/messages", methods=["POST"])
def send_message(conv_id: str):
    # ... validate ...

    store.add_message(conv_id, "user", content)

    if agent.is_running(conv_id):
        # Queue for later (optional: implement message queue)
        return jsonify({"status": "queued"}), 202

    # Start agent in background thread
    start_agent_background(conv_id)

    return jsonify({"status": "started"}), 200
```

### GET /api/conversations/{id}/stream

**Current:** Starts agent if not running, streams until done
**Proposed:** Subscribe only, streams indefinitely

```python
@bp.route("/<conv_id>/stream", methods=["GET"])
def stream_conversation(conv_id: str):
    """Subscribe to conversation events. Never starts work."""

    subscriber_queue = queue.Queue()
    pubsub.subscribe(conv_id, subscriber_queue)

    def generate():
        try:
            while True:
                try:
                    event = subscriber_queue.get(timeout=30)
                    yield f"event: {event['type']}\n"
                    yield f"data: {json.dumps(event)}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        except GeneratorExit:
            pass
        finally:
            pubsub.unsubscribe(conv_id, subscriber_queue)

    return Response(generate(), mimetype="text/event-stream")
```

---

## PubSub Implementation

### Single-Server (In-Memory)

```python
# web/pubsub.py

import queue
import threading
from collections import defaultdict

class PubSubHub:
    def __init__(self):
        self._subscribers: dict[str, list[queue.Queue]] = defaultdict(list)
        self._lock = threading.Lock()

    def subscribe(self, conv_id: str, q: queue.Queue) -> None:
        with self._lock:
            self._subscribers[conv_id].append(q)

    def unsubscribe(self, conv_id: str, q: queue.Queue) -> None:
        with self._lock:
            try:
                self._subscribers[conv_id].remove(q)
            except ValueError:
                pass

    def broadcast(self, conv_id: str, event: dict) -> int:
        """Broadcast event to all subscribers. Returns subscriber count."""
        with self._lock:
            subscribers = self._subscribers.get(conv_id, [])
            for q in subscribers:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass  # Slow consumer, drop event
            return len(subscribers)

    def subscriber_count(self, conv_id: str) -> int:
        with self._lock:
            return len(self._subscribers.get(conv_id, []))

# Global instance
hub = PubSubHub()
```

### Multi-Server (Redis)

For horizontal scaling, replace in-memory with Redis pub/sub:

```python
# web/pubsub_redis.py (future)

import redis
import json

class RedisPubSubHub:
    def __init__(self, redis_url: str):
        self._redis = redis.from_url(redis_url)
        self._local_subscribers: dict[str, list[queue.Queue]] = {}

    def subscribe(self, conv_id: str, q: queue.Queue) -> None:
        # Subscribe to Redis channel, forward to local queue
        ...

    def broadcast(self, conv_id: str, event: dict) -> None:
        # Publish to Redis channel
        self._redis.publish(f"conv:{conv_id}", json.dumps(event))
```

---

## Agent Runner Changes

The agent runner broadcasts events instead of yielding to a single stream:

```python
# web/agents/runner.py

from ..pubsub import hub

async def run_agent(conv_id: str, message: str, history: list):
    """Run agent and broadcast events to all subscribers."""

    hub.broadcast(conv_id, {"type": "system", "content": "Agent starting..."})

    try:
        async for event in agent.send_message(conv_id, message, history):
            # Store in database
            if event.type == "assistant":
                store.add_message(conv_id, "assistant", event.content)

            # Broadcast to all subscribers
            hub.broadcast(conv_id, event.to_dict())

    except Exception as e:
        hub.broadcast(conv_id, {"type": "error", "content": str(e)})

    finally:
        hub.broadcast(conv_id, {"type": "done", "conversation_id": conv_id})
```

---

## Frontend Changes

### Long-Lived Stream Connection

```javascript
// chat.js

let eventSource = null;

function connectStream(convId) {
    if (eventSource) {
        eventSource.close();
    }

    eventSource = new EventSource(`/api/conversations/${convId}/stream`);

    eventSource.addEventListener('assistant', (e) => {
        appendEvent('assistant', JSON.parse(e.data));
    });

    eventSource.addEventListener('done', (e) => {
        // Don't close - stay connected for future messages
        markFinalAnswer();
    });

    eventSource.onerror = () => {
        // Reconnect after delay
        setTimeout(() => connectStream(convId), 2000);
    };
}

// Connect when loading conversation
async function loadConversation(convId) {
    const conv = await fetch(`/api/conversations/${convId}`).then(r => r.json());
    renderMessages(conv.messages);
    connectStream(convId);  // Always connect, regardless of is_running
}

// Disconnect when leaving
function leaveConversation() {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
}
```

### Send Message (No Stream Start)

```javascript
async function sendMessage() {
    const message = input.value.trim();
    if (!message) return;

    // Optimistically show user message
    appendEvent('user', { content: message });
    input.value = '';

    // Send to server - stream is already connected
    const response = await fetch(`/api/conversations/${convId}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: message }),
    });

    if (!response.ok) {
        showError('Failed to send message');
    }
    // Response will arrive via the existing stream connection
}
```

---

## Message Queue (Optional Enhancement)

For handling messages sent while agent is running:

```python
# Simple in-memory queue per conversation
_pending_messages: dict[str, list[str]] = defaultdict(list)

def queue_message(conv_id: str, content: str):
    _pending_messages[conv_id].append(content)

def get_pending_messages(conv_id: str) -> list[str]:
    messages = _pending_messages.pop(conv_id, [])
    return messages

# In agent runner, after completing:
async def run_agent(conv_id: str, ...):
    # ... run agent ...

    # Check for queued messages
    pending = get_pending_messages(conv_id)
    if pending:
        # Process next message
        for msg in pending:
            store.add_message(conv_id, "user", msg)
        await run_agent(conv_id, pending[-1], updated_history)
```

---

## Migration Path

### Phase 1: Minimal Fix (Done)
- `/stream` checks if last message was answered
- Prevents duplicate responses on reconnect

### Phase 2: Separate Concerns
- Move agent start from `/stream` to `/messages`
- `/stream` becomes subscribe-only
- Add basic PubSub hub (in-memory)

### Phase 3: Long-Lived Connections
- Frontend keeps stream open indefinitely
- Reconnection logic with backoff
- Clean disconnect on navigation

### Phase 4: Multi-User Features (Optional)
- Show "X is typing" indicators
- Display other users' messages in real-time
- Message queue for concurrent sends

### Phase 5: Scale (If Needed)
- Redis pub/sub for multi-server
- Consider WebSockets for bidirectional communication

---

## HTMX Compatibility

HTMX supports SSE via the `sse` extension:

```html
<div hx-ext="sse" sse-connect="/api/conversations/123/stream">
    <div sse-swap="assistant" hx-swap="beforeend">
        <!-- Assistant messages append here -->
    </div>
</div>
```

However, for complex event handling (tool_use, tool_result, progress indicators), custom JavaScript may still be preferable. The current `chat.js` approach is compatible with the proposed architecture.

---

## Testing Considerations

```python
# tests/test_pubsub.py

def test_multiple_subscribers():
    hub = PubSubHub()
    q1, q2 = queue.Queue(), queue.Queue()

    hub.subscribe("conv-1", q1)
    hub.subscribe("conv-1", q2)

    hub.broadcast("conv-1", {"type": "test"})

    assert q1.get_nowait() == {"type": "test"}
    assert q2.get_nowait() == {"type": "test"}

def test_unsubscribe():
    hub = PubSubHub()
    q = queue.Queue()

    hub.subscribe("conv-1", q)
    hub.unsubscribe("conv-1", q)

    hub.broadcast("conv-1", {"type": "test"})

    assert q.empty()
```

---

## Decision Log

| Decision | Rationale |
|----------|-----------|
| In-memory first, Redis later | YAGNI - single server is sufficient now |
| Keep SSE over WebSockets | Simpler, sufficient for server→client push |
| Queue in memory | Database queue adds complexity; in-memory is fine for single server |
| Don't implement message queue yet | Current 409 on concurrent send is acceptable for now |
