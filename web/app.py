"""Matometa web application - Flask server with SSE streaming."""

import asyncio
import json
import logging
import os
import re
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request

from . import config
from .storage import store
from .agents import get_agent


# =============================================================================
# Knowledge Path Validation (Security Critical)
# =============================================================================

KNOWLEDGE_ROOT = (config.BASE_DIR / "knowledge").resolve()
KNOWLEDGE_DRAFTS_ROOT = config.BASE_DIR / "knowledge-drafts"
ALLOWED_EXTENSIONS = {".md"}


def validate_knowledge_path(file_param: str) -> Path | None:
    """
    Validate and resolve a knowledge file path.
    Returns None if invalid/unsafe.
    """
    if not file_param:
        return None

    # Reject obvious attacks early
    if ".." in file_param or file_param.startswith("/"):
        return None

    # Only allow simple alphanumeric + hyphen/underscore/dot + slash
    if not re.match(r'^[a-zA-Z0-9_\-./]+\.md$', file_param):
        return None

    # No double slashes, no hidden files
    if "//" in file_param or "/." in file_param:
        return None

    # Resolve full path
    candidate = (KNOWLEDGE_ROOT / file_param).resolve()

    # CRITICAL: ensure it's inside knowledge/
    try:
        candidate.relative_to(KNOWLEDGE_ROOT)
    except ValueError:
        return None  # Path escapes knowledge/

    # Must exist and be a file
    if not candidate.is_file():
        return None

    # Extension check (belt + suspenders)
    if candidate.suffix.lower() not in ALLOWED_EXTENSIONS:
        return None

    return candidate


def get_staging_dir(conv_id: str) -> Path:
    """Get staging directory for a knowledge conversation."""
    return KNOWLEDGE_DRAFTS_ROOT / conv_id


def list_staged_files(conv_id: str) -> list[str]:
    """List files in staging directory relative to knowledge root."""
    staging_dir = get_staging_dir(conv_id)
    if not staging_dir.exists():
        return []

    files = []
    for f in staging_dir.rglob("*.md"):
        try:
            rel_path = f.relative_to(staging_dir)
            files.append(str(rel_path))
        except ValueError:
            pass
    return sorted(files)

# Configure logging to file
logging.basicConfig(
    level=logging.DEBUG if config.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

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
                    "content": f"Écris un résumé concis EN FRANÇAIS (max 6 mots, sans guillemets) de cette demande:\n\n{user_message[:500]}"
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


def humanize_title(title: str) -> str:
    """Clean up a title: strip date prefix, ISO timestamps, separators; capitalize."""
    if not title:
        return title
    # Strip YYYY-MM- or YYYY-MM-DD- prefix
    title = re.sub(r"^\d{4}-\d{2}(-\d{2})?[-_]?", "", title)
    # Strip ISO 8601 timestamps like 2026-01-07T07:57:11.178085
    title = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?", "", title)
    # Replace dashes and underscores with spaces
    title = re.sub(r"[-_]+", " ", title)
    # Capitalize first letter
    if title:
        title = title[0].upper() + title[1:]
    return title.strip()


def get_sidebar_data():
    """Get data for sidebar (conversations only, reports are now in DB)."""
    # Recent conversations with report info
    conversations = store.list_conversations(limit=10)
    agent = get_agent_instance()

    # Check running status for each conversation using the proper interface
    running_ids = []
    for conv in conversations:
        if conv.title:
            conv.title = humanize_title(conv.title)
        conv.is_running = agent.is_running(conv.id)
        if conv.is_running:
            running_ids.append(conv.id)

    return {"conversations": conversations, "running_ids": running_ids}


@app.route("/")
def index():
    """Redirect to explorations."""
    data = get_sidebar_data()
    return render_template("explorations.html", section="explorations", **data)


@app.route("/explorations")
def explorations():
    """Explorations section - chat interface."""
    data = get_sidebar_data()
    current_conv_id = request.args.get("conv")
    current_conv = None
    if current_conv_id:
        current_conv = store.get_conversation(current_conv_id, include_messages=False)
        if current_conv and current_conv.title:
            current_conv.title = humanize_title(current_conv.title)
    return render_template("explorations.html", section="explorations", current_conv=current_conv, **data)


def list_knowledge_files() -> dict[str, list[dict]]:
    """List all knowledge files grouped by category."""
    categories = {}

    for category_dir in sorted(KNOWLEDGE_ROOT.iterdir()):
        if not category_dir.is_dir() or category_dir.name.startswith("."):
            continue

        files = []
        for f in sorted(category_dir.rglob("*.md")):
            rel_path = f.relative_to(KNOWLEDGE_ROOT)
            files.append({
                "path": str(rel_path),
                "name": humanize_title(f.stem),
                "modified": f.stat().st_mtime,
            })

        if files:
            categories[category_dir.name] = files

    return categories


@app.route("/connaissances")
def connaissances():
    """Connaissances section - knowledge file browser."""
    data = get_sidebar_data()
    file_param = request.args.get("file")
    conv_id = request.args.get("conv")

    current_file = None
    file_content = None
    current_conv = None
    staged_files = []

    if file_param:
        # Validate the file path
        validated_path = validate_knowledge_path(file_param)
        if validated_path:
            current_file = file_param
            file_content = validated_path.read_text()

            # Check for active conversation on this file
            if conv_id:
                current_conv = store.get_conversation(conv_id, include_messages=False)
            else:
                current_conv = store.get_active_knowledge_conversation(file_param)

            # Get staged files if conversation exists
            if current_conv:
                staged_files = list_staged_files(current_conv.id)
        else:
            # Invalid path - redirect to list
            return render_template(
                "connaissances.html",
                section="connaissances",
                error="Fichier non trouvé",
                categories=list_knowledge_files(),
                active_conversations=store.list_active_knowledge_conversations(),
                **data
            )

    # Get categories for list view
    categories = list_knowledge_files()

    # Get active knowledge conversations to show badges
    active_conversations = store.list_active_knowledge_conversations()
    active_files = {c.file_path: c for c in active_conversations if c.file_path}

    return render_template(
        "connaissances.html",
        section="connaissances",
        categories=categories,
        current_file=current_file,
        file_content=file_content,
        current_conv=current_conv,
        staged_files=staged_files,
        active_files=active_files,
        active_conversations=active_conversations,
        **data
    )


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

    agent = get_agent_instance()
    return jsonify(
        {
            **conv.to_dict(),
            "is_running": agent.is_running(conv_id),
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
    agent = get_agent_instance()
    return jsonify(
        {
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
        }
    )


@app.route("/api/running", methods=["GET"])
def get_running_conversations():
    """Get list of currently running conversation IDs."""
    agent = get_agent_instance()
    running_ids = list(agent._running) if hasattr(agent, '_running') else []
    return jsonify({"running": running_ids})


@app.route("/api/conversations/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    """Delete a conversation."""
    if store.delete_conversation(conv_id):
        # Return empty response for htmx to remove the element
        return "", 200
    return jsonify({"error": "Conversation not found"}), 404


@app.route("/api/conversations/<conv_id>", methods=["PATCH"])
def update_conversation_api(conv_id: str):
    """Update conversation (title, etc.)."""
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    title = data.get("title")
    if title is not None:
        store.update_conversation(conv_id, title=title)
        return jsonify({"title": title})

    return jsonify({"error": "No valid fields to update"}), 400


@app.route("/api/conversations/<conv_id>/generate-title", methods=["POST"])
def generate_title_api(conv_id: str):
    """Generate a title for a conversation using LLM."""
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    # Collect context: first 2 user messages + last assistant message
    user_messages = []
    last_assistant_msg = None
    for msg in conv.messages:
        if msg.type == "user" and len(user_messages) < 2:
            user_messages.append(msg.content[:300])
        if msg.type == "assistant":
            last_assistant_msg = msg.content[:500]

    if not user_messages:
        return jsonify({"error": "No user message to generate title from"}), 400

    # Build context
    context_parts = []
    for i, um in enumerate(user_messages, 1):
        context_parts.append(f"Message utilisateur {i}: {um}")
    if last_assistant_msg:
        context_parts.append(f"Dernière réponse: {last_assistant_msg}")
    context = "\n\n".join(context_parts)

    # Generate title synchronously (blocking for API response)
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
                "content": f"Écris un titre court et direct (4-8 mots) sur le thème de cette conversation. En français uniquement. Pas de guillemets.\n\n{context}"
            }]
        )
        title = response.content[0].text.strip().strip('"\'')[:60]
        store.update_conversation(conv_id, title=title)
        return jsonify({"title": title})

    except Exception as e:
        logger.error(f"Failed to generate title: {e}")
        return jsonify({"error": str(e)}), 500


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

    # CRITICAL: Don't start a new agent run if one is already running
    agent = get_agent_instance()
    if agent.is_running(conv_id):
        # Return a "waiting" stream that just sends keepalives
        # The client should eventually get the real response when ready
        def wait_stream():
            yield f"event: system\n"
            yield f"data: {json.dumps({'content': 'Agent already running, please wait...'})}\n\n"
            # Keep connection alive but don't start new agent
            import time
            for _ in range(60):  # Wait up to 60 seconds
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

    # Get the last user message
    last_message = None
    for msg in reversed(conv.messages):
        if msg.type == "user":
            last_message = msg.content
            break

    if not last_message:
        return jsonify({"error": "No user message to respond to"}), 400

    # Inject knowledge editing context for knowledge conversations
    if conv.conv_type == "knowledge" and conv.file_path:
        staging_dir = get_staging_dir(conv_id)
        original_path = KNOWLEDGE_ROOT / conv.file_path
        staged_path = staging_dir / conv.file_path

        # Check if this is the first user message (no prior user messages in history)
        is_first_message = not any(m.type == "user" for m in conv.messages[:-1])

        if is_first_message:
            # Read current file content for first message
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
            # For follow-up messages, just remind about the staging directory
            knowledge_context = f"""(Reminder: write changes to {staged_path})

User request: """

        last_message = knowledge_context + last_message

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

                    # Store tool events for replay
                    if event.type in ("tool_use", "tool_result"):
                        content = json.dumps(event.content) if isinstance(event.content, dict) else str(event.content)
                        store.add_message(conv_id, event.type, content)

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
        title=metadata.get("query category", "Rapport sans titre"),
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
# API Routes - Knowledge
# -----------------------------------------------------------------------------


@app.route("/api/knowledge", methods=["GET"])
def list_knowledge_api():
    """List all knowledge files."""
    categories = list_knowledge_files()
    return jsonify({"categories": categories})


@app.route("/api/knowledge/files/<path:file_path>", methods=["GET"])
def get_knowledge_file(file_path: str):
    """Get a knowledge file's content."""
    validated_path = validate_knowledge_path(file_path)
    if not validated_path:
        return jsonify({"error": "Invalid or non-existent file path"}), 404

    return jsonify({
        "path": file_path,
        "content": validated_path.read_text(),
        "modified": validated_path.stat().st_mtime,
    })


@app.route("/api/knowledge/files/<path:file_path>/conversation", methods=["POST"])
def start_knowledge_conversation(file_path: str):
    """Start or resume a knowledge editing conversation."""
    validated_path = validate_knowledge_path(file_path)
    if not validated_path:
        return jsonify({"error": "Invalid or non-existent file path"}), 404

    # Check for existing active conversation
    existing = store.get_active_knowledge_conversation(file_path)
    if existing:
        return jsonify({
            "id": existing.id,
            "resumed": True,
            "staged_files": list_staged_files(existing.id),
            "links": {
                "self": f"/api/conversations/{existing.id}",
                "stream": f"/api/conversations/{existing.id}/stream",
                "commit": f"/api/knowledge/conversations/{existing.id}/commit",
                "abandon": f"/api/knowledge/conversations/{existing.id}/abandon",
            },
        })

    # Create new conversation
    conv = store.create_conversation(conv_type="knowledge", file_path=file_path)

    # Create staging directory
    staging_dir = get_staging_dir(conv.id)
    staging_dir.mkdir(parents=True, exist_ok=True)

    # Copy original file to staging
    staged_file = staging_dir / file_path
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(validated_path, staged_file)

    return jsonify({
        "id": conv.id,
        "resumed": False,
        "staged_files": [file_path],
        "links": {
            "self": f"/api/conversations/{conv.id}",
            "stream": f"/api/conversations/{conv.id}/stream",
            "commit": f"/api/knowledge/conversations/{conv.id}/commit",
            "abandon": f"/api/knowledge/conversations/{conv.id}/abandon",
        },
    })


@app.route("/api/knowledge/conversations/<conv_id>/files", methods=["GET"])
def get_staged_files(conv_id: str):
    """Get list of staged files for a knowledge conversation."""
    conv = store.get_conversation(conv_id, include_messages=True)
    if not conv or conv.conv_type != "knowledge":
        return jsonify({"error": "Knowledge conversation not found"}), 404

    # Get first user message for default summary
    first_user_message = None
    for msg in conv.messages:
        if msg.type == "user":
            first_user_message = msg.content[:200]  # Truncate for prompt
            break

    return jsonify({
        "files": list_staged_files(conv_id),
        "conversation_id": conv_id,
        "first_user_message": first_user_message,
    })


@app.route("/api/knowledge/conversations/<conv_id>/commit", methods=["POST"])
def commit_knowledge_changes(conv_id: str):
    """Commit staged changes to knowledge directory."""
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return jsonify({"error": "Knowledge conversation not found"}), 404

    if conv.status != "active":
        return jsonify({"error": "Conversation is not active"}), 400

    staging_dir = get_staging_dir(conv_id)
    if not staging_dir.exists():
        return jsonify({"error": "No staged files"}), 400

    staged_files = list_staged_files(conv_id)
    if not staged_files:
        return jsonify({"error": "No staged files"}), 400

    # Get commit summary from request (optional)
    data = request.get_json() or {}
    summary = data.get("summary", "Knowledge update")

    # Copy staged files to knowledge directory
    committed_files = []
    for rel_path in staged_files:
        src = staging_dir / rel_path
        dst = KNOWLEDGE_ROOT / rel_path
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            committed_files.append(rel_path)

    # Prepend to JOURNAL.md (new entries on top)
    journal_path = config.BASE_DIR / "JOURNAL.md"
    files_list = ", ".join(committed_files)
    date_str = datetime.now().strftime("%Y-%m-%d")
    journal_entry = f"- {date_str}. {summary} ({files_list})\n"

    # Read existing content and prepend new entry after the header
    existing = journal_path.read_text() if journal_path.exists() else ""
    # Find the end of the header (after the blockquote section)
    header_end = existing.find("\n\n- ")
    if header_end == -1:
        # No entries yet, find end of header by looking for double newline after blockquote
        header_end = existing.find("\n\n", existing.find(">"))
        if header_end == -1:
            header_end = len(existing)

    new_content = existing[:header_end] + "\n\n" + journal_entry + existing[header_end + 2:]
    journal_path.write_text(new_content)

    # Clean up staging directory
    shutil.rmtree(staging_dir, ignore_errors=True)

    # Update conversation status
    store.update_conversation(conv_id, status="committed")

    return jsonify({
        "status": "committed",
        "files": committed_files,
        "conversation_id": conv_id,
    })


@app.route("/api/knowledge/conversations/<conv_id>/abandon", methods=["POST"])
def abandon_knowledge_changes(conv_id: str):
    """Abandon staged changes and close conversation."""
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return jsonify({"error": "Knowledge conversation not found"}), 404

    if conv.status != "active":
        return jsonify({"error": "Conversation is not active"}), 400

    # Clean up staging directory
    staging_dir = get_staging_dir(conv_id)
    shutil.rmtree(staging_dir, ignore_errors=True)

    # Update conversation status
    store.update_conversation(conv_id, status="abandoned")

    return jsonify({
        "status": "abandoned",
        "conversation_id": conv_id,
    })


@app.route("/api/knowledge/conversations/<conv_id>/preview/<path:file_path>")
def preview_staged_file(conv_id: str, file_path: str):
    """Preview a staged file as rendered HTML."""
    import markdown

    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return "Knowledge conversation not found", 404

    staging_dir = get_staging_dir(conv_id)
    staged_file = staging_dir / file_path

    if not staged_file.exists():
        return "Staged file not found", 404

    # Read and render markdown
    content = staged_file.read_text()
    html_content = markdown.markdown(content, extensions=["fenced_code", "tables", "toc"])

    # Return a simple HTML page with the rendered content
    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <title>Aperçu: {file_path}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css">
    <style>
        body {{ padding: 2rem; max-width: 800px; margin: 0 auto; }}
        pre {{ background: #f8f9fa; padding: 1rem; border-radius: 0.5rem; overflow-x: auto; }}
        code {{ font-size: 0.875rem; }}
        table {{ width: 100%; margin-bottom: 1rem; }}
        th, td {{ padding: 0.5rem; border: 1px solid #dee2e6; }}
    </style>
</head>
<body>
    <nav class="mb-4">
        <small class="text-muted">{file_path}</small>
    </nav>
    <article class="markdown-body">
        {html_content}
    </article>
</body>
</html>"""


# -----------------------------------------------------------------------------
# API Routes - Logs
# -----------------------------------------------------------------------------


@app.route("/api/logs")
def stream_logs():
    """Stream agent logs via SSE (tail -f style)."""
    lines = request.args.get("lines", 50, type=int)

    def generate():
        # First, send last N lines
        try:
            with open(config.LOG_FILE, "r") as f:
                all_lines = f.readlines()
                for line in all_lines[-lines:]:
                    yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
        except FileNotFoundError:
            yield f"data: {json.dumps({'line': '[No logs yet]'})}\n\n"

        # Then tail the file
        try:
            with open(config.LOG_FILE, "r") as f:
                f.seek(0, 2)  # Go to end
                while True:
                    line = f.readline()
                    if line:
                        yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
                    else:
                        time.sleep(0.5)
                        yield ": keepalive\n\n"
        except GeneratorExit:
            pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/logs/recent")
def get_recent_logs():
    """Get recent log lines (non-streaming)."""
    lines = request.args.get("lines", 100, type=int)
    try:
        with open(config.LOG_FILE, "r") as f:
            all_lines = f.readlines()
            return jsonify({"lines": [l.rstrip() for l in all_lines[-lines:]]})
    except FileNotFoundError:
        return jsonify({"lines": []})


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
