"""Conversation API routes."""

import asyncio
import json
import logging
import threading
import time

from fastapi import APIRouter, Depends, Query, Request, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .. import config, llm
from ..config import ADMIN_USERS
from ..deps import get_current_user
from ..signals import signals
from ..storage import store
from ..uploads import (
    AVScanFailedError,
    BlockedFileTypeError,
    FileTooLargeError,
    copy_file_for_modification,
    format_file_for_context,
    get_file_content,
)
from ..uploads import (
    upload_file as do_upload_file,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations")


def generate_conversation_title(user_message: str, conv_id: str) -> None:
    """Generate a smart title for a conversation (async, in background)."""

    def _generate():
        try:
            model = config.OLLAMA_TITLE_MODEL if config.LLM_BACKEND in ("ollama", "cli-ollama") else config.CLAUDE_MODEL
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
- meta: Question sur Autometa lui-même
"""

    VALID_TAGS = {
        "emplois",
        "dora",
        "marche",
        "communaute",
        "pilotage",
        "plateforme",
        "rdv-insertion",
        "mon-recap",
        "multi",
        "matomo",
        "stats",
        "datalake",
        "candidats",
        "prescripteurs",
        "employeurs",
        "structures",
        "acheteurs",
        "fournisseurs",
        "iae",
        "orientation",
        "depot-de-besoin",
        "demande-de-devis",
        "commandes",
        "trafic",
        "conversions",
        "retention",
        "geographique",
        "extraction",
        "analyse",
        "appli",
        "meta",
    }

    prompt = f"""Analyse cette demande utilisateur et attribue des tags parmi la taxonomie suivante.

{TAG_TAXONOMY}

Règles:
- OBLIGATOIRE: exactement 1 tag produit
- OBLIGATOIRE: exactement 1 tag type_demande
- OPTIONNEL: 0 à 2 tags thème (acteurs, concepts, métriques)
- Si la demande mentionne plusieurs produits, utilise "multi"
- Si c'est une question sur l'outil Autometa, utilise "meta"

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
            model = config.OLLAMA_TAG_MODEL if config.LLM_BACKEND in ("ollama", "cli-ollama") else config.CLAUDE_MODEL
            response = llm.generate_text(prompt, model=model, max_tokens=100)
            tag_names = _parse_tags(response)
            if tag_names:
                store.set_conversation_tags(conv_id, tag_names)
                logger.info(f"Auto-tagged conversation {conv_id}: {tag_names}")
        except Exception as exc:
            logger.warning(f"Failed to generate tags: {exc}")

    threading.Thread(target=_generate, daemon=True).start()


@router.post("")
def create_conversation(user_email: str = Depends(get_current_user)):
    """Create a new conversation."""
    conv = store.create_conversation(user_id=user_email)
    return {
        "id": conv.id,
        "links": {
            "self": f"/api/conversations/{conv.id}",
            "messages": f"/api/conversations/{conv.id}/messages",
            "stream": f"/api/conversations/{conv.id}/stream",
        },
    }


@router.get("")
def list_conversations(user_email: str = Depends(get_current_user), limit: int = 20):
    """List recent conversations."""
    convs = store.list_conversations(limit=limit, user_id=user_email)
    return {
        "conversations": [
            {
                "id": c.id,
                "title": c.title,
                "has_report": c.has_report,
                "is_running": c.needs_response,
                "updated_at": c.updated_at.isoformat(),
                "links": {"self": f"/api/conversations/{c.id}"},
            }
            for c in convs
        ]
    }


@router.get("/running")
def get_running():
    """Get list of currently running conversation IDs (needs_response=True)."""
    return {"running": store.get_running_conversation_ids()}


@router.get("/{conv_id}")
def get_conversation(conv_id: str, user_email: str = Depends(get_current_user)):
    """Get a conversation with all messages.

    Allows read-only access to any conversation (shared via UUID link).
    Returns is_owner flag to indicate if current user owns the conversation.
    """
    conv = store.get_conversation(conv_id)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    is_owner = conv.user_id == user_email or conv.user_id is None

    return {
        **conv.to_dict(),
        "is_running": conv.needs_response,
        "is_owner": is_owner,
        "links": {
            "self": f"/api/conversations/{conv_id}",
            "messages": f"/api/conversations/{conv_id}/messages",
            "stream": f"/api/conversations/{conv_id}/stream",
        },
    }


@router.delete("/{conv_id}")
def delete_conversation(conv_id: str, user_email: str = Depends(get_current_user)):
    """Delete a conversation. User must be owner or admin."""
    conv = store.get_conversation(conv_id)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    is_admin = user_email in ADMIN_USERS
    is_owner = conv.user_id == user_email
    if not is_admin and not is_owner:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    if store.delete_conversation(conv_id):
        return Response(status_code=200)
    return JSONResponse({"error": "Failed to delete"}, status_code=500)


@router.post("/{conv_id}/pin")
async def pin_conversation(conv_id: str, request: Request, user_email: str = Depends(get_current_user)):
    """Pin a conversation to the sidebar. Admin only."""
    if user_email not in ADMIN_USERS:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    body = await request.body()
    data = (await request.json()) if body else {}
    label = data.get("label", "").strip() or conv.title or "Sans titre"

    if store.pin_conversation(conv_id, label):
        return {"ok": True, "label": label}
    return JSONResponse({"error": "Failed to pin"}, status_code=500)


@router.delete("/{conv_id}/pin")
def unpin_conversation(conv_id: str, user_email: str = Depends(get_current_user)):
    """Unpin a conversation from the sidebar. Admin only."""
    if user_email not in ADMIN_USERS:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    if store.unpin_conversation(conv_id):
        return {"ok": True}
    return JSONResponse({"error": "Failed to unpin"}, status_code=500)


@router.patch("/{conv_id}")
async def update_conversation(conv_id: str, request: Request):
    """Update conversation (title, etc.)."""
    data = await request.json()
    if not data:
        return JSONResponse({"error": "No data provided"}, status_code=400)

    title = data.get("title")
    if title is not None:
        store.update_conversation(conv_id, title=title)
        return {"title": title}

    return JSONResponse({"error": "No valid fields to update"}, status_code=400)


@router.post("/{conv_id}/generate-title")
def generate_title(conv_id: str):
    """Generate a title for a conversation using LLM."""
    conv = store.get_conversation(conv_id)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

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
        return JSONResponse({"error": "No user message to generate title from"}, status_code=400)

    context_parts = []
    for i, um in enumerate(user_messages, 1):
        context_parts.append(f"Message utilisateur {i}: {um}")
    if last_assistant_msg:
        context_parts.append(f"Derniere reponse: {last_assistant_msg}")
    context = "\n\n".join(context_parts)

    try:
        model = config.OLLAMA_TITLE_MODEL if config.LLM_BACKEND in ("ollama", "cli-ollama") else config.CLAUDE_MODEL
        prompt = (
            "Ecris un titre court et direct (6-10 mots) sur le theme de cette conversation. "
            "En francais uniquement. Pas de guillemets.\n\n"
            f"{context}"
        )
        title = llm.generate_text(prompt, model=model, max_tokens=50).strip().strip("\"'")[:100]
        store.update_conversation(conv_id, title=title)
        return {"title": title}

    except Exception as exc:
        logger.error(f"Failed to generate title: {exc}")
        return JSONResponse({"error": "Failed to generate title"}, status_code=500)


@router.post("/{conv_id}/fork")
def fork_conversation(conv_id: str, user_email: str = Depends(get_current_user)):
    """Fork (deep copy) a conversation.

    Creates a new conversation owned by the current user with all messages copied.
    The original conversation is unchanged.
    """
    if not user_email:
        return JSONResponse({"error": "Authentication required"}, status_code=401)

    source = store.get_conversation(conv_id, include_messages=False)
    if not source:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    new_conv = store.fork_conversation(conv_id, user_email)
    if not new_conv:
        return JSONResponse({"error": "Failed to fork conversation"}, status_code=500)

    return {
        "id": new_conv.id,
        "forked_from": conv_id,
        "links": {
            "self": f"/api/conversations/{new_conv.id}",
            "view": f"/explorations/{new_conv.id}",
        },
    }


@router.post("/{conv_id}/messages")
async def send_message(conv_id: str, request: Request, user_email: str = Depends(get_current_user)):
    """Send a message to start agent processing.

    Only the conversation owner can send messages. Shared conversations are read-only.
    """
    conv = store.get_conversation(conv_id)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    # Check ownership - only owner can send messages
    if conv.user_id and conv.user_id != user_email:
        return JSONResponse(
            {
                "error": "Cette conversation appartient à un autre utilisateur. Vous pouvez la consulter mais pas y ajouter de messages."
            },
            status_code=403,
        )

    data = await request.json()
    if not data or "content" not in data:
        return JSONResponse({"error": "Missing 'content' field"}, status_code=400)

    content = data["content"]

    if conv.needs_response:
        return JSONResponse({"error": "Conversation already running"}, status_code=409)

    is_first_message = len(conv.messages) == 0
    user_msg = store.add_message(conv_id, "user", content)
    store.update_conversation(conv_id, needs_response=True)

    if is_first_message:
        generate_conversation_title(content, conv_id)
        generate_conversation_tags(content, conv_id)

    # Build history and prompt for the PM
    history = []
    for msg in conv.messages:
        if msg.type in ("user", "assistant"):
            history.append({"role": msg.type, "content": msg.content})

    prompt = content

    # Inject knowledge editing context for knowledge conversations
    if conv.conv_type == "knowledge" and conv.file_path:
        from ..helpers import KNOWLEDGE_ROOT, get_staging_dir

        staging_dir = get_staging_dir(conv_id)
        original_path = (KNOWLEDGE_ROOT / conv.file_path).resolve()
        staged_path = (staging_dir / conv.file_path).resolve()

        # Path traversal protection
        if not str(original_path).startswith(str(KNOWLEDGE_ROOT.resolve())) or not str(staged_path).startswith(
            str(staging_dir.resolve())
        ):
            return JSONResponse({"error": "Invalid file path"}, status_code=400)

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

        prompt = knowledge_context + prompt

    # Enqueue the run command for the process manager
    store.enqueue_pm_command(
        conv_id,
        "run",
        {
            "prompt": prompt,
            "history": history,
            "session_id": conv.session_id,
            "user_email": user_email,
        },
    )

    return {
        "status": "started",
        "after_id": user_msg.id if user_msg else 0,
        "links": {
            "stream": f"/api/conversations/{conv_id}/stream",
            "cancel": f"/api/conversations/{conv_id}/cancel",
        },
    }


@router.post("/{conv_id}/relaunch")
async def relaunch_conversation(conv_id: str, user_email: str = Depends(get_current_user)):
    """Admin-only: relaunch a stuck conversation by re-sending the last user message."""
    if user_email not in config.ADMIN_USERS:
        return JSONResponse({"error": "Admin only"}, status_code=403)

    conv = store.get_conversation(conv_id)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)
    if conv.needs_response:
        return JSONResponse({"error": "Conversation already running"}, status_code=409)

    # Find the last user message
    last_user_msg = None
    for msg in reversed(conv.messages):
        if msg.type == "user":
            last_user_msg = msg
            break
    if not last_user_msg:
        return JSONResponse({"error": "No user message found"}, status_code=400)

    # Build history (all messages before the last user message)
    history = []
    for msg in conv.messages:
        if msg.id >= last_user_msg.id:
            break
        if msg.type in ("user", "assistant"):
            history.append({"role": msg.type, "content": msg.content})

    store.update_conversation(conv_id, needs_response=True)
    store.enqueue_pm_command(
        conv_id,
        "run",
        {
            "prompt": last_user_msg.content,
            "history": history,
            "session_id": conv.session_id,
            "user_email": conv.user_id,
        },
    )

    return {"status": "relaunched", "after_id": last_user_msg.id}


@router.get("/{conv_id}/stream")
async def stream_conversation(
    conv_id: str,
    after: int = Query(default=0),
    user_email: str = Depends(get_current_user),
):
    """Stream agent responses via Server-Sent Events.

    Uses in-process signals (web/signals.py) for near-instant message
    delivery, with a 5s DB fallback for robustness. Client disconnect
    does NOT kill the agent.

    The ``after`` query parameter tells the handler where to start streaming
    from (the ID of the last message the client already has).  This prevents
    a race condition where the PM writes messages between the client's POST
    and the SSE connect — without ``after``, those messages would be skipped.
    """
    conv = store.get_conversation(conv_id, include_messages=after == 0)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    if after == 0 and not conv.messages:
        return JSONResponse({"error": "No messages in conversation"}, status_code=400)

    def _sse_event(msg_type: str, data: dict) -> str:
        """Format a complete SSE event as a single string (avoids split-chunk buffering)."""
        return f"event: {msg_type}\ndata: {json.dumps(data)}\n\n"

    def _format_msg(msg) -> str:
        """Format a DB message as an SSE event string."""
        sse_data = {"type": msg.type, "content": msg.content}
        if msg.type in ("tool_use", "tool_result"):
            try:
                sse_data["content"] = json.loads(msg.content)
            except (json.JSONDecodeError, TypeError):
                pass
        return _sse_event(msg.type, sse_data)

    async def _drain_unseen(last_msg_id: int) -> list[str]:
        """Fetch remaining messages and return formatted SSE chunks ending with 'done'."""
        chunks = []
        final = await asyncio.to_thread(store.get_messages_since, conv_id, last_msg_id)
        for msg in final:
            chunks.append(_format_msg(msg))
        chunks.append(_sse_event("done", {"conversation_id": conv_id}))
        return chunks

    async def generate():
        last_msg_id = after if after > 0 else (conv.messages[-1].id if conv.messages else 0)
        logger.debug(
            "SSE stream start: conv=%s, after=%d, watermark=%d",
            conv_id,
            after,
            last_msg_id,
        )
        max_seconds = 300
        fallback_interval = 5  # safety-net DB poll every 5s
        start = time.monotonic()
        last_fallback = start

        try:
            # Check if conversation is already complete (PM finished before
            # SSE connects, or conversation was never running)
            if signals.is_finished(conv_id) or not conv.needs_response:
                for chunk in await _drain_unseen(last_msg_id):
                    yield chunk
                return

            while (time.monotonic() - start) < max_seconds:
                signaled = await signals.wait_for_message(conv_id, timeout=3.0)
                now = time.monotonic()

                if signaled:
                    new_messages = await asyncio.to_thread(store.get_messages_since, conv_id, last_msg_id)
                    for msg in new_messages:
                        last_msg_id = msg.id
                        yield _format_msg(msg)

                # Completion check: in-memory flag (0 queries)
                if signals.is_finished(conv_id):
                    for chunk in await _drain_unseen(last_msg_id):
                        yield chunk
                    return

                # Safety-net fallback: check DB every 5s for missed signals
                if not signaled and (now - last_fallback) >= fallback_interval:
                    last_fallback = now
                    new_messages = await asyncio.to_thread(store.get_messages_since, conv_id, last_msg_id)
                    for msg in new_messages:
                        last_msg_id = msg.id
                        yield _format_msg(msg)

                    updated = await asyncio.to_thread(store.get_conversation, conv_id, False)
                    if updated and not updated.needs_response:
                        for chunk in await _drain_unseen(last_msg_id):
                            yield chunk
                        return

                # PM liveness: in-memory cache (0 queries)
                if not signals.is_pm_alive():
                    yield _sse_event("error", {"content": "L'agent est indisponible"})
                    yield _sse_event("done", {"conversation_id": conv_id})
                    return

                # Heartbeat keeps proxies alive (only when idle — skip if we just yielded content)
                if not signaled:
                    yield _sse_event("heartbeat", {})

            yield _sse_event("error", {"content": "Timeout waiting for agent"})
        finally:
            signals.cleanup(conv_id)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/{conv_id}/cancel")
def cancel_conversation(conv_id: str):
    """Cancel a running conversation via the process manager.

    If no pending run command exists for this conversation (PM already picked it
    up or crashed), force-clear needs_response so the conversation unsticks.
    """
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or not conv.needs_response:
        return {"status": "not_running"}

    store.enqueue_pm_command(conv_id, "cancel")

    # If there's no pending run command, the PM either already finished
    # (and failed to clear the flag) or crashed. Force-clear to unstick.
    pending = store.get_pending_pm_commands()
    has_pending_run = any(cmd["conversation_id"] == conv_id and cmd["command"] == "run" for cmd in pending)
    if not has_pending_run:
        store.update_conversation(conv_id, needs_response=False)
        store.add_message(conv_id, "assistant", "*Interrompu.*")

    return {"status": "cancelled"}


@router.get("/{conv_id}/tags")
def get_conversation_tags(conv_id: str):
    """Get tags for a conversation."""
    tags = store.get_conversation_tags(conv_id)
    return {"tags": [{"name": t.name, "type": t.type, "label": t.label} for t in tags]}


@router.put("/{conv_id}/tags")
async def set_conversation_tags(conv_id: str, request: Request):
    """Set tags for a conversation (replaces existing)."""
    data = await request.json()
    if not data or "tags" not in data:
        return JSONResponse({"error": "Missing 'tags' field"}, status_code=400)

    tag_names = data["tags"]
    if not isinstance(tag_names, list):
        return JSONResponse({"error": "'tags' must be a list"}, status_code=400)

    store.set_conversation_tags(conv_id, tag_names)
    tags = store.get_conversation_tags(conv_id)
    return {"tags": [{"name": t.name, "type": t.type, "label": t.label} for t in tags]}


# =============================================================================
# File Upload Endpoints
# =============================================================================


@router.post("/{conv_id}/files")
async def upload_file_endpoint(conv_id: str, file: UploadFile, user_email: str = Depends(get_current_user)):
    """Upload a file to a conversation.

    Accepts multipart/form-data with 'file' field.
    Returns file metadata and optional text content for small text files.
    """
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    # Check ownership
    if conv.user_id and conv.user_id != user_email:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    # Check conversation type
    if conv.conv_type == "report":
        return JSONResponse({"error": "Cannot upload files to report conversations"}, status_code=400)

    if not file.filename:
        return JSONResponse({"error": "No file selected"}, status_code=400)

    try:
        uploaded_file, text_content = do_upload_file(
            file_obj=file.file,
            filename=file.filename,
            conversation_id=conv_id,
            user_id=user_email,
            check_duplicate=True,
        )

        response = {
            "file": uploaded_file.to_dict(),
            "text_content": text_content,
            "context_message": format_file_for_context(uploaded_file, text_content),
        }
        return JSONResponse(response, status_code=201)

    except FileTooLargeError as e:
        logger.warning("File too large: %s", e)
        return JSONResponse({"error": "File too large"}, status_code=413)
    except BlockedFileTypeError as e:
        logger.warning("Blocked file type: %s", e)
        return JSONResponse({"error": "File type not allowed"}, status_code=415)
    except AVScanFailedError as e:
        logger.warning("AV scan failed: %s", e)
        return JSONResponse({"error": "File failed security scan"}, status_code=422)
    except Exception as e:
        logger.error(f"File upload failed: {e}")
        return JSONResponse({"error": "Upload failed"}, status_code=500)


@router.get("/{conv_id}/files")
def list_files(conv_id: str):
    """List all files uploaded to a conversation."""
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv:
        return JSONResponse({"error": "Conversation not found"}, status_code=404)

    files = store.get_conversation_files(conv_id)
    return {"files": [f.to_dict() for f in files]}


@router.get("/{conv_id}/files/{file_id}")
def get_file(conv_id: str, file_id: int):
    """Get metadata for a specific uploaded file."""
    uploaded_file = store.get_uploaded_file(file_id)
    if not uploaded_file:
        return JSONResponse({"error": "File not found"}, status_code=404)

    if uploaded_file.conversation_id != conv_id:
        return JSONResponse({"error": "File not in this conversation"}, status_code=404)

    return {"file": uploaded_file.to_dict()}


@router.get("/{conv_id}/files/{file_id}/content")
def get_file_content_endpoint(conv_id: str, file_id: int):
    """Download the content of an uploaded file."""
    uploaded_file = store.get_uploaded_file(file_id)
    if not uploaded_file:
        return JSONResponse({"error": "File not found"}, status_code=404)

    if uploaded_file.conversation_id != conv_id:
        return JSONResponse({"error": "File not in this conversation"}, status_code=404)

    content = get_file_content(uploaded_file)
    if content is None:
        return JSONResponse({"error": "File content not available"}, status_code=404)

    return Response(
        content=content,
        media_type=uploaded_file.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{uploaded_file.original_filename}"'},
    )


@router.post("/{conv_id}/files/{file_id}/copy")
async def copy_file(conv_id: str, file_id: int, request: Request, user_email: str = Depends(get_current_user)):
    """Create a writable copy of an uploaded file for modification.

    Used when the user asks the agent to modify a file.
    The original remains read-only.
    """
    uploaded_file = store.get_uploaded_file(file_id)
    if not uploaded_file:
        return JSONResponse({"error": "File not found"}, status_code=404)

    if uploaded_file.conversation_id != conv_id:
        return JSONResponse({"error": "File not in this conversation"}, status_code=404)

    # Check ownership
    conv = store.get_conversation(conv_id, include_messages=False)
    if conv and conv.user_id and conv.user_id != user_email:
        return JSONResponse({"error": "Permission denied"}, status_code=403)

    body = await request.body()
    data = (await request.json()) if body else {}
    new_filename = data.get("filename")

    copy_path = copy_file_for_modification(uploaded_file, new_filename=new_filename)
    if copy_path is None:
        return JSONResponse({"error": "Failed to create copy"}, status_code=500)

    return {
        "copy_path": str(copy_path),
        "original_file": uploaded_file.to_dict(),
    }
