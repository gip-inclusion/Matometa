"""Matometa web application - Flask server with SSE streaming."""

import asyncio
import json
import os
import re
import threading
from flask import Flask, Response, jsonify, render_template, request

from . import config
from .storage import store
from .agents import get_agent

app = Flask(__name__)


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
                    "content": f"Write a concise summary (max 6 words, no quotes) of this user request:\n\n{user_message[:500]}"
                }]
            )
            title = response.content[0].text.strip()[:60]
            if title:
                store.update_conversation(conv_id, title=title)
        except Exception as e:
            app.logger.warning(f"Failed to generate title: {e}")

    # Run in background thread to not block response
    threading.Thread(target=_generate, daemon=True).start()


# Global agent instance
_agent = None


def get_agent_instance():
    """Get or create the agent backend instance."""
    global _agent
    if _agent is None:
        _agent = get_agent()
    return _agent


# -----------------------------------------------------------------------------
# HTML Routes
# -----------------------------------------------------------------------------


def get_sidebar_data():
    """Get data for sidebar (conversations only, reports are now in DB)."""
    # Recent conversations with report info
    conversations = store.list_conversations(limit=10)
    return {"conversations": conversations}


@app.route("/")
def index():
    """Redirect to explorations."""
    data = get_sidebar_data()
    return render_template("explorations.html", section="explorations", **data)


@app.route("/explorations")
def explorations():
    """Explorations section - chat interface."""
    data = get_sidebar_data()
    current_conv = request.args.get("conv")
    return render_template("explorations.html", section="explorations", current_conv=current_conv, **data)


@app.route("/connaissances")
def connaissances():
    """Connaissances section - placeholder."""
    data = get_sidebar_data()
    return render_template("connaissances.html", section="connaissances", **data)


# -----------------------------------------------------------------------------
# API Routes - Conversations
# -----------------------------------------------------------------------------


@app.route("/api/conversations", methods=["POST"])
def create_conversation():
    """Create a new conversation."""
    conv = store.create_conversation(user_id=None)  # No auth yet
    return jsonify(
        {
            "id": conv.id,
            "links": {
                "self": f"/api/conversations/{conv.id}",
                "messages": f"/api/conversations/{conv.id}/messages",
                "stream": f"/api/conversations/{conv.id}/stream",
            },
        }
    )


@app.route("/api/conversations/<conv_id>", methods=["GET"])
def get_conversation(conv_id: str):
    """Get a conversation with all messages."""
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    return jsonify(
        {
            **conv.to_dict(),
            "links": {
                "self": f"/api/conversations/{conv_id}",
                "messages": f"/api/conversations/{conv_id}/messages",
                "stream": f"/api/conversations/{conv_id}/stream",
            },
        }
    )


@app.route("/api/conversations", methods=["GET"])
def list_conversations_api():
    """List recent conversations."""
    limit = request.args.get("limit", 20, type=int)
    convs = store.list_conversations(limit=limit)
    return jsonify(
        {
            "conversations": [
                {
                    "id": c.id,
                    "title": c.title,
                    "has_report": c.has_report,
                    "updated_at": c.updated_at.isoformat(),
                    "links": {"self": f"/api/conversations/{c.id}"},
                }
                for c in convs
            ]
        }
    )


@app.route("/api/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    """Delete a conversation."""
    if store.delete_conversation(conv_id):
        return jsonify({"status": "deleted"})
    return jsonify({"error": "Conversation not found"}), 404


# -----------------------------------------------------------------------------
# API Routes - Messages
# -----------------------------------------------------------------------------


@app.route("/api/conversations/<conv_id>/messages", methods=["POST"])
def send_message(conv_id: str):
    """Send a message to start agent processing."""
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Missing 'content' field"}), 400

    content = data["content"]

    # Check if already running
    agent = get_agent_instance()
    if agent.is_running(conv_id):
        return jsonify({"error": "Conversation already running"}), 409

    # Add user message to conversation
    is_first_message = len(conv.messages) == 0
    store.add_message(conv_id, "user", content)

    # Generate smart title for new conversations (in background)
    if is_first_message:
        generate_conversation_title(content, conv_id)

    return jsonify(
        {
            "status": "started",
            "links": {
                "stream": f"/api/conversations/{conv_id}/stream",
                "cancel": f"/api/conversations/{conv_id}/cancel",
            },
        }
    )


@app.route("/api/conversations/<conv_id>/stream", methods=["GET"])
def stream_conversation(conv_id: str):
    """Stream agent responses via Server-Sent Events."""
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    if not conv.messages:
        return jsonify({"error": "No messages in conversation"}), 400

    # Get the last user message
    last_message = None
    for msg in reversed(conv.messages):
        if msg.type == "user":
            last_message = msg.content
            break

    if not last_message:
        return jsonify({"error": "No user message to respond to"}), 400

    def generate():
        """Generate SSE events from agent."""
        agent = get_agent_instance()

        # Get history (excluding the last user message we're responding to)
        history = []
        for msg in conv.messages[:-1]:
            if msg.type in ("user", "assistant"):
                history.append({"role": msg.type, "content": msg.content})

        # Collect all events for the assistant response
        all_events = []
        assistant_text_parts = []

        # Run async generator in sync context using a queue
        import queue
        import threading

        event_queue = queue.Queue()
        error_holder = [None]

        def run_async():
            """Run the async generator in a dedicated thread with its own event loop."""
            async def collect_events():
                try:
                    async for event in agent.send_message(
                        conversation_id=conv_id,
                        message=last_message,
                        history=history,
                        session_id=conv.session_id,
                    ):
                        event_queue.put(("event", event))

                        # Capture session_id from system init message
                        if event.type == "system" and event.raw.get("subtype") == "init":
                            new_session_id = event.raw.get("session_id")
                            if new_session_id:
                                store.update_conversation(conv_id, session_id=new_session_id)

                except Exception as e:
                    error_holder[0] = e
                finally:
                    event_queue.put(("done", None))

            asyncio.run(collect_events())

        # Start async processing in background thread
        thread = threading.Thread(target=run_async, daemon=True)
        thread.start()

        # Yield events as they arrive
        while True:
            try:
                msg_type, event = event_queue.get(timeout=120)  # 2 min timeout

                if msg_type == "done":
                    break

                if event:
                    all_events.append(event.raw)

                    # Collect assistant text
                    if event.type == "assistant":
                        assistant_text_parts.append(str(event.content))

                    # Yield SSE event
                    yield f"event: {event.type}\n"
                    yield f"data: {json.dumps(event.to_dict())}\n\n"

            except queue.Empty:
                # Timeout - send keepalive
                yield ": keepalive\n\n"

        # Check for errors
        if error_holder[0]:
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': str(error_holder[0])})}\n\n"

        # Wait for thread to finish
        thread.join(timeout=5)

        # Save assistant response to conversation
        if assistant_text_parts:
            full_response = "\n".join(assistant_text_parts)
            msg = store.add_message(conv_id, "assistant", full_response)

            # Check if this is a report (has YAML front-matter)
            if msg and full_response.startswith("---\n"):
                _maybe_create_report(conv_id, msg.id, full_response, last_message)

        # Send done event
        yield "event: done\n"
        yield f"data: {json.dumps({'conversation_id': conv_id})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


def _maybe_create_report(conv_id: str, message_id: int, content: str, original_query: str) -> None:
    """Create a report record if the assistant message contains a report."""
    # Parse YAML front-matter
    match = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if not match:
        return

    front_matter = match.group(1)
    metadata = {}
    for line in front_matter.split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            metadata[key.strip().lower()] = value.strip()

    # Check if this looks like a report
    if "query category" not in metadata:
        return

    store.create_report(
        conv_id=conv_id,
        message_id=message_id,
        title=metadata.get("query category", "Untitled Report"),
        website=metadata.get("website"),
        category=metadata.get("query category"),
        original_query=original_query,
    )


@app.route("/api/conversations/<conv_id>/cancel", methods=["POST"])
def cancel_conversation(conv_id: str):
    """Cancel a running conversation."""
    agent = get_agent_instance()

    # Run cancel with asyncio.run for proper context management
    cancelled = asyncio.run(agent.cancel(conv_id))

    if cancelled:
        return jsonify({"status": "cancelled"})
    else:
        return jsonify({"status": "not_running"})


# -----------------------------------------------------------------------------
# API Routes - Reports
# -----------------------------------------------------------------------------


@app.route("/api/reports", methods=["GET"])
def list_reports():
    """List available reports from database."""
    website = request.args.get("website")
    category = request.args.get("category")
    limit = request.args.get("limit", 50, type=int)

    reports = store.list_reports(website=website, category=category, limit=limit)
    return jsonify(
        {
            "reports": [
                {
                    "id": r.id,
                    "title": r.title,
                    "website": r.website,
                    "category": r.category,
                    "conversation_id": r.conversation_id,
                    "version": r.version,
                    "updated_at": r.updated_at.isoformat(),
                    "links": {
                        "self": f"/api/reports/{r.id}",
                        "conversation": f"/api/conversations/{r.conversation_id}",
                    },
                }
                for r in reports
            ]
        }
    )


@app.route("/api/reports/<int:report_id>", methods=["GET"])
def get_report(report_id: int):
    """Get a specific report."""
    report = store.get_report(report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404

    # Get the message content (the actual report)
    messages = store.get_messages(report.conversation_id)
    report_content = None
    for msg in messages:
        if msg.id == report.message_id:
            report_content = msg.content
            break

    return jsonify(
        {
            "id": report.id,
            "title": report.title,
            "website": report.website,
            "category": report.category,
            "tags": report.tags,
            "original_query": report.original_query,
            "version": report.version,
            "content": report_content,
            "conversation_id": report.conversation_id,
            "created_at": report.created_at.isoformat(),
            "updated_at": report.updated_at.isoformat(),
            "links": {
                "conversation": f"/api/conversations/{report.conversation_id}",
            },
        }
    )


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def main():
    """Run the development server."""
    print(f"Starting Matometa web server at http://{config.HOST}:{config.PORT}")
    print(f"Agent backend: {config.AGENT_BACKEND}")
    print(f"Working directory: {config.BASE_DIR}")
    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)


if __name__ == "__main__":
    main()
