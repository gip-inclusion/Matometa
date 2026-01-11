"""Conversation API routes."""

import asyncio
import json
import logging
import queue
import re
import threading
import os

from flask import Blueprint, Response, jsonify, request, g

from ..storage import store
from ..agents import get_agent
from .. import config

logger = logging.getLogger(__name__)

bp = Blueprint("conversations", __name__, url_prefix="/api/conversations")

# Global agent instance
_agent = None


def get_agent_instance():
    """Get or create the agent backend instance."""
    global _agent
    if _agent is None:
        _agent = get_agent()
    return _agent


def generate_conversation_title(user_message: str, conv_id: str) -> None:
    """Generate a smart title for a conversation using Claude (async, in background)."""
    try:
        from anthropic import Anthropic
    except ImportError:
        return

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return

    def _generate():
        try:
            client = Anthropic(api_key=api_key)
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=50,
                messages=[{
                    "role": "user",
                    "content": f"Ecris un resume concis EN FRANCAIS (max 6 mots, sans guillemets) de cette demande:\n\n{user_message[:500]}"
                }]
            )
            title = response.content[0].text.strip()[:60]
            if title:
                store.update_conversation(conv_id, title=title)
        except Exception as e:
            logger.warning(f"Failed to generate title: {e}")

    threading.Thread(target=_generate, daemon=True).start()


@bp.route("", methods=["POST"])
def create_conversation():
    """Create a new conversation."""
    user_email = getattr(g, "user_email", None)
    conv = store.create_conversation(user_id=user_email)
    return jsonify({
        "id": conv.id,
        "links": {
            "self": f"/api/conversations/{conv.id}",
            "messages": f"/api/conversations/{conv.id}/messages",
            "stream": f"/api/conversations/{conv.id}/stream",
        },
    })


@bp.route("", methods=["GET"])
def list_conversations():
    """List recent conversations."""
    limit = request.args.get("limit", 20, type=int)
    convs = store.list_conversations(limit=limit, user_id=g.user_email)
    agent = get_agent_instance()
    return jsonify({
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "has_report": c.has_report,
                "is_running": agent.is_running(c.id),
                "updated_at": c.updated_at.isoformat(),
                "links": {"self": f"/api/conversations/{c.id}"},
            }
            for c in convs
        ]
    })


@bp.route("/<conv_id>", methods=["GET"])
def get_conversation(conv_id: str):
    """Get a conversation with all messages."""
    conv = store.get_conversation(conv_id, user_id=g.user_email)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    agent = get_agent_instance()
    return jsonify({
        **conv.to_dict(),
        "is_running": agent.is_running(conv_id),
        "links": {
            "self": f"/api/conversations/{conv_id}",
            "messages": f"/api/conversations/{conv_id}/messages",
            "stream": f"/api/conversations/{conv_id}/stream",
        },
    })


@bp.route("/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    """Delete a conversation."""
    if store.delete_conversation(conv_id):
        return "", 200
    return jsonify({"error": "Conversation not found"}), 404


@bp.route("/<conv_id>", methods=["PATCH"])
def update_conversation(conv_id: str):
    """Update conversation (title, etc.)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    title = data.get("title")
    if title is not None:
        store.update_conversation(conv_id, title=title)
        return jsonify({"title": title})

    return jsonify({"error": "No valid fields to update"}), 400


@bp.route("/<conv_id>/generate-title", methods=["POST"])
def generate_title(conv_id: str):
    """Generate a title for a conversation using LLM."""
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    user_messages = []
    last_assistant_msg = None
    for msg in conv.messages:
        if msg.type == "user" and len(user_messages) < 2:
            user_messages.append(msg.content[:300])
        if msg.type == "assistant":
            last_assistant_msg = msg.content[:500]

    # For reports without user messages, use original_query or report title
    if not user_messages and conv.report:
        if conv.report.original_query:
            user_messages.append(conv.report.original_query[:300])
        elif conv.report.title:
            user_messages.append(conv.report.title)

    if not user_messages:
        return jsonify({"error": "No user message to generate title from"}), 400

    context_parts = []
    for i, um in enumerate(user_messages, 1):
        context_parts.append(f"Message utilisateur {i}: {um}")
    if last_assistant_msg:
        context_parts.append(f"Derniere reponse: {last_assistant_msg}")
    context = "\n\n".join(context_parts)

    try:
        from anthropic import Anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            return jsonify({"error": "ANTHROPIC_API_KEY not set"}), 500

        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=50,
            messages=[{
                "role": "user",
                "content": f"Ecris un titre court et direct (4-8 mots) sur le theme de cette conversation. En francais uniquement. Pas de guillemets.\n\n{context}"
            }]
        )
        title = response.content[0].text.strip().strip('"\'')[:60]
        store.update_conversation(conv_id, title=title)
        return jsonify({"title": title})

    except Exception as e:
        logger.error(f"Failed to generate title: {e}")
        return jsonify({"error": str(e)}), 500


@bp.route("/<conv_id>/messages", methods=["POST"])
def send_message(conv_id: str):
    """Send a message to start agent processing."""
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' field"}), 400

    content = data["content"]
    agent = get_agent_instance()

    if agent.is_running(conv_id):
        return jsonify({"error": "Conversation already running"}), 409

    is_first_message = len(conv.messages) == 0
    store.add_message(conv_id, "user", content)

    if is_first_message:
        generate_conversation_title(content, conv_id)

    return jsonify({
        "status": "started",
        "links": {
            "stream": f"/api/conversations/{conv_id}/stream",
            "cancel": f"/api/conversations/{conv_id}/cancel",
        },
    })


@bp.route("/<conv_id>/stream", methods=["GET"])
def stream_conversation(conv_id: str):
    """Stream agent responses via Server-Sent Events."""
    from ..helpers import get_staging_dir, KNOWLEDGE_ROOT
    from ..audit import audit_log

    conv = store.get_conversation(conv_id, user_id=g.user_email)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    if not conv.messages:
        return jsonify({"error": "No messages in conversation"}), 400

    agent = get_agent_instance()
    user_email = getattr(g, "user_email", None)

    # Check if last user message was already responded to
    last_user_msg = None
    has_response = False
    for msg in conv.messages:
        if msg.type == "user":
            last_user_msg = msg.content
            has_response = False
        elif msg.type == "assistant" and last_user_msg is not None:
            has_response = True

    # If already responded and agent not running, nothing to stream
    if has_response and not agent.is_running(conv_id):
        def done_stream():
            yield f"event: done\n"
            yield f"data: {json.dumps({'conversation_id': conv_id})}\n\n"
        return Response(
            done_stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if agent.is_running(conv_id):
        def wait_stream():
            yield f"event: system\n"
            yield f"data: {json.dumps({'content': 'Agent already running, please wait...'})}\n\n"
            import time
            for _ in range(60):
                time.sleep(1)
                if not agent.is_running(conv_id):
                    yield f"event: done\n"
                    yield f"data: {json.dumps({'conversation_id': conv_id})}\n\n"
                    return
                yield ": keepalive\n\n"
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': 'Timeout waiting for agent'})}\n\n"

        return Response(
            wait_stream(),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if not last_user_msg:
        return jsonify({"error": "No user message to respond to"}), 400

    last_message = last_user_msg

    # Inject knowledge editing context for knowledge conversations
    if conv.conv_type == "knowledge" and conv.file_path:
        staging_dir = get_staging_dir(conv.id)
        original_path = KNOWLEDGE_ROOT / conv.file_path
        staged_path = staging_dir / conv.file_path

        is_first_message = not any(m.type == "user" for m in conv.messages[:-1])

        if is_first_message:
            if staged_path.exists():
                file_content = staged_path.read_text()
            elif original_path.exists():
                file_content = original_path.read_text()
            else:
                file_content = "(fichier introuvable)"

            knowledge_context = f"""You are editing a knowledge file.

IMPORTANT: Write ALL changes to the staging directory:
  {staging_dir}/

The original file is at: knowledge/{conv.file_path}
Your working copy is at: {staged_path}

Current content of {conv.file_path}:
---
{file_content}
---

User request: """
        else:
            knowledge_context = f"""(Reminder: write changes to {staged_path})

User request: """

        last_message = knowledge_context + last_message

    def generate():
        history = []
        for msg in conv.messages[:-1]:
            if msg.type in ("user", "assistant"):
                history.append({"role": msg.type, "content": msg.content})

        event_queue = queue.Queue()
        error_holder = [None]

        def run_async():
            # Storage state - lives in the async thread, independent of SSE
            assistant_text_parts = []
            assistant_msg_id = None

            async def collect_events():
                nonlocal assistant_text_parts, assistant_msg_id

                try:
                    async for event in agent.send_message(
                        conversation_id=conv_id,
                        message=last_message,
                        history=history,
                        session_id=conv.session_id,
                    ):
                        # Store to database FIRST (survives client disconnect)
                        if event.type == "assistant":
                            assistant_text_parts.append(str(event.content))
                            full_text = "\n".join(assistant_text_parts)
                            if assistant_msg_id is None:
                                msg = store.add_message(conv_id, "assistant", full_text)
                                assistant_msg_id = msg.id if msg else None
                            else:
                                store.update_message(assistant_msg_id, full_text)

                        if event.type in ("tool_use", "tool_result"):
                            # Finalize current assistant message so next text creates a new one
                            if event.type == "tool_use":
                                assistant_msg_id = None
                                assistant_text_parts = []

                            content = json.dumps(event.content) if isinstance(event.content, dict) else str(event.content)
                            store.add_message(conv_id, event.type, content)

                        if event.type == "system" and event.raw.get("subtype") == "init":
                            new_session_id = event.raw.get("session_id")
                            if new_session_id:
                                store.update_conversation(conv_id, session_id=new_session_id)

                        # Then queue for SSE (may fail if client disconnected - that's OK)
                        event_queue.put(("event", event))

                except Exception as e:
                    error_holder[0] = e
                finally:
                    event_queue.put(("done", None))

            asyncio.run(collect_events())

        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()

        while True:
            try:
                msg_type, event = event_queue.get(timeout=120)

                if msg_type == "done":
                    break

                if event:
                    # Audit log tool usage (still in generator for now)
                    if event.type == "tool_use":
                        tool_data = event.content if isinstance(event.content, dict) else {}
                        audit_log(
                            conversation_id=conv_id,
                            user_email=user_email,
                            tool_name=tool_data.get("tool", "unknown"),
                            tool_input=tool_data.get("input", {}),
                        )

                    yield f"event: {event.type}\n"
                    yield f"data: {json.dumps(event.to_dict())}\n\n"

            except queue.Empty:
                yield ": keepalive\n\n"

        if error_holder[0]:
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': str(error_holder[0])})}\n\n"

        thread.join(timeout=5)

        yield "event: done\n"
        yield f"data: {json.dumps({'conversation_id': conv_id})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@bp.route("/<conv_id>/cancel", methods=["POST"])
def cancel_conversation(conv_id: str):
    """Cancel a running conversation."""
    agent = get_agent_instance()
    cancelled = asyncio.run(agent.cancel(conv_id))

    if cancelled:
        return jsonify({"status": "cancelled"})
    else:
        return jsonify({"status": "not_running"})


@bp.route("/running", methods=["GET"])
def get_running():
    """Get list of currently running conversation IDs."""
    agent = get_agent_instance()
    running_ids = list(agent._running) if hasattr(agent, '_running') else []
    return jsonify({"running": running_ids})
