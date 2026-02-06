"""Conversation API routes."""

import asyncio
import json
import logging
import queue
import threading
from flask import Blueprint, Response, jsonify, request, g

from ..storage import store
from ..agents import get_agent
from .. import config
from .. import llm
from ..config import ADMIN_USERS
from lib.tool_taxonomy import classify_tool
from lib.api_signals import parse_api_signals

logger = logging.getLogger(__name__)

bp = Blueprint("conversations", __name__, url_prefix="/api/conversations")

# Global agent instance
_agent = None

# Persistent event loop for async operations (avoids "Future attached to different loop" errors)
_async_loop = None
_async_thread = None
_loop_lock = threading.Lock()


def _get_async_loop():
    """Get or create a persistent event loop running in a background thread."""
    global _async_loop, _async_thread

    with _loop_lock:
        if _async_loop is not None and _async_loop.is_running():
            return _async_loop

        _async_loop = asyncio.new_event_loop()
        started = threading.Event()

        def run_loop():
            asyncio.set_event_loop(_async_loop)
            _async_loop.call_soon(started.set)  # Signal we're running
            _async_loop.run_forever()

        _async_thread = threading.Thread(target=run_loop, daemon=True)
        _async_thread.start()
        started.wait(timeout=5)  # Wait until loop is actually running

    return _async_loop


def get_agent_instance():
    """Get or create the agent backend instance."""
    global _agent
    if _agent is None:
        _agent = get_agent()
    return _agent


def generate_conversation_title(user_message: str, conv_id: str) -> None:
    """Generate a smart title for a conversation (async, in background)."""
    def _generate():
        try:
            model = config.OLLAMA_TITLE_MODEL if config.LLM_BACKEND == "ollama" else config.CLAUDE_MODEL
            prompt = (
                "Ecris un resume concis EN FRANCAIS (max 10 mots, sans guillemets) "
                f"de cette demande:\n\n{user_message[:500]}"
            )
            title = llm.generate_text(prompt, model=model, max_tokens=50).strip()[:100]
            if title:
                store.update_conversation(conv_id, title=title)
        except Exception as exc:
            logger.warning(f"Failed to generate title: {exc}")

    threading.Thread(target=_generate, daemon=True).start()


def generate_conversation_tags(user_message: str, conv_id: str) -> None:
    """Auto-tag a conversation (async, in background).

    Uses the configured LLM backend to analyze the first user message and
    assign relevant tags from the predefined taxonomy.
    Runs in a background thread.
    """
    import subprocess

    # Tag taxonomy (must match database _seed_tags)
    TAG_TAXONOMY = """
## Produits (choisir 1 seul, obligatoire)
- emplois: Les Emplois de l'inclusion
- dora: Dora (annuaire de services)
- marche: Le Marché de l'inclusion
- communaute: La Communauté de l'inclusion
- pilotage: Pilotage de l'inclusion
- plateforme: inclusion.gouv.fr (site vitrine)
- rdv-insertion: RDV-Insertion
- mon-recap: Mon Récap
- multi: Multi-produits (concerne plusieurs produits)

## Thèmes - Acteurs (0 à 2)
- candidats: Candidats / demandeurs d'emploi
- prescripteurs: Prescripteurs
- employeurs: Employeurs / SIAE
- structures: Structures / SIAE (angle organisation)
- acheteurs: Acheteurs (Marché)
- fournisseurs: Fournisseurs (Marché)

## Thèmes - Concepts métier (0 à 2)
- iae: IAE en général
- orientation: Orientation
- depot-de-besoin: Dépôt de besoin (Marché)
- demande-de-devis: Demande de devis (Marché)
- commandes: Commandes (Mon Récap)

## Thèmes - Métriques (0 à 2)
- trafic: Analyse de trafic
- conversions: Conversions / funnel
- retention: Rétention / fidélisation
- geographique: Analyse géographique

## Type de demande (choisir 1 seul, obligatoire)
- extraction: Extraction de données brutes
- analyse: Analyse / rapport
- appli: Application interactive
- meta: Question sur Matometa lui-même
"""

    VALID_TAGS = {
        "emplois", "dora", "marche", "communaute", "pilotage",
        "plateforme", "rdv-insertion", "mon-recap", "multi",
        "matomo", "stats", "datalake",
        "candidats", "prescripteurs", "employeurs", "structures",
        "acheteurs", "fournisseurs",
        "iae", "orientation", "depot-de-besoin", "demande-de-devis", "commandes",
        "trafic", "conversions", "retention", "geographique",
        "extraction", "analyse", "appli", "meta",
    }

    prompt = f"""Analyse cette demande utilisateur et attribue des tags parmi la taxonomie suivante.

{TAG_TAXONOMY}

Règles:
- OBLIGATOIRE: exactement 1 tag produit
- OBLIGATOIRE: exactement 1 tag type_demande
- OPTIONNEL: 0 à 2 tags thème (acteurs, concepts, métriques)
- Si la demande mentionne plusieurs produits, utilise "multi"
- Si c'est une question sur l'outil Matometa, utilise "meta"

Demande: {user_message[:1000]}

Réponds UNIQUEMENT avec les noms des tags séparés par des virgules, rien d'autre.
Exemple: emplois, candidats, trafic, analyse"""

    def _parse_tags(response: str) -> list[str]:
        """Extract valid tag names from response."""
        # Handle potential explanation text - take just the tag line
        if "\n" in response:
            for line in response.split("\n"):
                if "," in line and not line.startswith("#"):
                    response = line
                    break

        tag_names = []
        for part in response.replace("\n", ",").split(","):
            tag = part.strip().lower().strip(".-*")
            if tag in VALID_TAGS:
                tag_names.append(tag)
        return tag_names

    def _generate():
        """Generate tags using the configured LLM backend."""
        try:
            model = config.OLLAMA_TAG_MODEL if config.LLM_BACKEND == "ollama" else config.CLAUDE_MODEL
            response = llm.generate_text(prompt, model=model, max_tokens=100)
            tag_names = _parse_tags(response)
            if tag_names:
                store.set_conversation_tags(conv_id, tag_names)
                logger.info(f"Auto-tagged conversation {conv_id}: {tag_names}")
        except Exception as exc:
            logger.warning(f"Failed to generate tags: {exc}")

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
    """Get a conversation with all messages.

    Allows read-only access to any conversation (shared via UUID link).
    Returns is_owner flag to indicate if current user owns the conversation.
    """
    # Allow read-only access to any conversation (no user_id filter)
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    user_email = getattr(g, "user_email", None)
    is_owner = conv.user_id == user_email or conv.user_id is None

    agent = get_agent_instance()
    return jsonify({
        **conv.to_dict(),
        "is_running": agent.is_running(conv_id),
        "is_owner": is_owner,
        "links": {
            "self": f"/api/conversations/{conv_id}",
            "messages": f"/api/conversations/{conv_id}/messages",
            "stream": f"/api/conversations/{conv_id}/stream",
        },
    })


@bp.route("/<conv_id>", methods=["DELETE"])
def delete_conversation(conv_id: str):
    """Delete a conversation. User must be owner or admin."""
    user_email = getattr(g, "user_email", None)
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    # Check permission: must be owner or admin
    is_admin = user_email in ADMIN_USERS
    is_owner = conv.user_id == user_email
    if not is_admin and not is_owner:
        return jsonify({"error": "Permission denied"}), 403

    if store.delete_conversation(conv_id):
        return "", 200
    return jsonify({"error": "Failed to delete"}), 500


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
        model = config.OLLAMA_TITLE_MODEL if config.LLM_BACKEND == "ollama" else config.CLAUDE_MODEL
        prompt = (
            "Ecris un titre court et direct (6-10 mots) sur le theme de cette conversation. "
            "En francais uniquement. Pas de guillemets.\n\n"
            f"{context}"
        )
        title = llm.generate_text(prompt, model=model, max_tokens=50).strip().strip('"\'')[:100]
        store.update_conversation(conv_id, title=title)
        return jsonify({"title": title})

    except Exception as exc:
        logger.error(f"Failed to generate title: {exc}")
        return jsonify({"error": str(exc)}), 500


@bp.route("/<conv_id>/fork", methods=["POST"])
def fork_conversation(conv_id: str):
    """Fork (deep copy) a conversation.

    Creates a new conversation owned by the current user with all messages copied.
    The original conversation is unchanged.
    """
    user_email = getattr(g, "user_email", None)
    if not user_email:
        return jsonify({"error": "Authentication required"}), 401

    # Check source conversation exists
    source = store.get_conversation(conv_id, include_messages=False)
    if not source:
        return jsonify({"error": "Conversation not found"}), 404

    # Fork the conversation
    new_conv = store.fork_conversation(conv_id, user_email)
    if not new_conv:
        return jsonify({"error": "Failed to fork conversation"}), 500

    return jsonify({
        "id": new_conv.id,
        "forked_from": conv_id,
        "links": {
            "self": f"/api/conversations/{new_conv.id}",
            "view": f"/explorations/{new_conv.id}",
        },
    })


@bp.route("/<conv_id>/messages", methods=["POST"])
def send_message(conv_id: str):
    """Send a message to start agent processing.

    Only the conversation owner can send messages. Shared conversations are read-only.
    """
    conv = store.get_conversation(conv_id)
    if not conv:
        return jsonify({"error": "Conversation not found"}), 404

    # Check ownership - only owner can send messages
    user_email = getattr(g, "user_email", None)
    if conv.user_id and conv.user_id != user_email:
        return jsonify({"error": "Cette conversation appartient à un autre utilisateur. Vous pouvez la consulter mais pas y ajouter de messages."}), 403

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
        generate_conversation_tags(content, conv_id)

    return jsonify({
        "status": "started",
        "links": {
            "stream": f"/api/conversations/{conv_id}/stream",
            "cancel": f"/api/conversations/{conv_id}/cancel",
        },
    })


@bp.route("/<conv_id>/stream", methods=["GET"])
def stream_conversation(conv_id: str):
    """Stream agent responses via Server-Sent Events.

    Allows streaming for shared conversations (read-only view of existing responses).
    New agent runs are still restricted to the owner via send_message.
    """
    from ..helpers import get_staging_dir, KNOWLEDGE_ROOT
    from ..audit import audit_log

    # Allow streaming for any conversation (read-only access to existing messages)
    conv = store.get_conversation(conv_id)
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

        # Storage state - lives in the async context, independent of SSE
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
                        append_mode = bool(getattr(event, "raw", {}).get("append"))
                        if append_mode:
                            full_text = "".join(assistant_text_parts)
                        else:
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

                        # Add taxonomy category to tool_use events
                        if event.type == "tool_use" and isinstance(event.content, dict):
                            tool_name = event.content.get("tool", "")
                            tool_input = event.content.get("input", {})
                            category = classify_tool(tool_name, tool_input)
                            enriched = {**event.content, "category": category}
                            content = json.dumps(enriched)
                            # Attach enriched content for SSE
                            event._sse_content = enriched
                        # Parse API signals from tool_result events
                        elif event.type == "tool_result":
                            raw_content = str(event.content) if not isinstance(event.content, str) else event.content
                            api_calls = parse_api_signals(raw_content)
                            if api_calls:
                                enriched = {
                                    "output": event.content,
                                    "api_calls": api_calls,
                                }
                                content = json.dumps(enriched)
                                # Attach enriched content for SSE
                                event._sse_content = enriched
                            else:
                                content = json.dumps(event.content) if isinstance(event.content, dict) else str(event.content)
                        else:
                            content = json.dumps(event.content) if isinstance(event.content, dict) else str(event.content)

                        store.add_message(conv_id, event.type, content)

                    if event.type == "system":
                        # Handle session ID from init event
                        if event.raw.get("subtype") == "init":
                            new_session_id = event.raw.get("session_id")
                            if new_session_id:
                                store.update_conversation(conv_id, session_id=new_session_id)

                        # Extract and store token usage from result event
                        if event.raw.get("usage"):
                            usage = event.raw["usage"]
                            # Build extra dict for non-core usage fields
                            extra = {}
                            if usage.get("service_tier"):
                                extra["service_tier"] = usage["service_tier"]
                            if usage.get("web_search_requests"):
                                extra["web_search_requests"] = usage["web_search_requests"]

                            store.accumulate_usage(
                                conv_id,
                                input_tokens=usage.get("input_tokens", 0),
                                output_tokens=usage.get("output_tokens", 0),
                                cache_creation_tokens=usage.get("cache_creation_input_tokens", 0),
                                cache_read_tokens=usage.get("cache_read_input_tokens", 0),
                                backend=config.AGENT_BACKEND,
                                extra=extra if extra else None,
                            )

                    # Then queue for SSE (may fail if client disconnected - that's OK)
                    event_queue.put(("event", event))

            except Exception as e:
                error_holder[0] = e
            finally:
                event_queue.put(("done", None))

        # Submit to persistent event loop (avoids "Future attached to different loop" errors)
        loop = _get_async_loop()
        if not loop.is_running():
            logger.error("Event loop not running, cannot process conversation")
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': 'Internal error: event loop not available'})}\n\n"
            yield "event: done\n"
            yield f"data: {json.dumps({'conversation_id': conv_id})}\n\n"
            return

        future = asyncio.run_coroutine_threadsafe(collect_events(), loop)

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

                    # Use enriched content if available (tool_use with category, tool_result with api_calls)
                    if hasattr(event, '_sse_content'):
                        sse_data = {"type": event.type, "content": event._sse_content}
                    else:
                        sse_data = event.to_dict()

                    yield f"event: {event.type}\n"
                    yield f"data: {json.dumps(sse_data)}\n\n"

            except queue.Empty:
                yield ": keepalive\n\n"

        if error_holder[0]:
            yield f"event: error\n"
            yield f"data: {json.dumps({'error': str(error_holder[0])})}\n\n"

        # Wait for the async task to fully complete (cleanup subprocess handles, etc.)
        try:
            future.result(timeout=5)
        except asyncio.CancelledError:
            logger.warning(f"Conversation {conv_id} was cancelled")
        except asyncio.InvalidStateError:
            logger.error(f"Conversation {conv_id}: event loop died mid-execution")
        except Exception as e:
            if error_holder[0] is None:
                error_holder[0] = e
                yield f"event: error\n"
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

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
    loop = _get_async_loop()
    future = asyncio.run_coroutine_threadsafe(agent.cancel(conv_id), loop)
    cancelled = future.result(timeout=10)

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


@bp.route("/<conv_id>/tags", methods=["GET"])
def get_conversation_tags(conv_id: str):
    """Get tags for a conversation."""
    tags = store.get_conversation_tags(conv_id)
    return jsonify({
        "tags": [{"name": t.name, "type": t.type, "label": t.label} for t in tags]
    })


@bp.route("/<conv_id>/tags", methods=["PUT"])
def set_conversation_tags(conv_id: str):
    """Set tags for a conversation (replaces existing)."""
    data = request.get_json()
    if not data or "tags" not in data:
        return jsonify({"error": "Missing 'tags' field"}), 400

    tag_names = data["tags"]
    if not isinstance(tag_names, list):
        return jsonify({"error": "'tags' must be a list"}), 400

    store.set_conversation_tags(conv_id, tag_names)
    tags = store.get_conversation_tags(conv_id)
    return jsonify({
        "tags": [{"name": t.name, "type": t.type, "label": t.label} for t in tags]
    })
