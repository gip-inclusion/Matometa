"""Knowledge API routes."""

import html as html_mod
import logging
import shutil

import markdown
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse

from ..database import store
from ..deps import get_current_user
from ..github import GitHubClient, GitHubError
from ..helpers import (
    get_staging_dir,
    list_knowledge_files,
    list_staged_files,
    validate_knowledge_path,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/knowledge")


@router.get("")
def list_knowledge():
    categories = list_knowledge_files()
    return {"categories": categories}


@router.get("/files/{file_path:path}")
def get_knowledge_file(file_path: str):
    validated_path = validate_knowledge_path(file_path)
    if not validated_path:
        return JSONResponse({"error": "Invalid or non-existent file path"}, status_code=404)

    return {
        "path": file_path,
        "content": validated_path.read_text(),
        "modified": validated_path.stat().st_mtime,
    }


@router.post("/files/{file_path:path}/conversation")
def start_knowledge_conversation(file_path: str, user_email: str = Depends(get_current_user)):
    """Start or resume a knowledge editing conversation."""
    validated_path = validate_knowledge_path(file_path)
    if not validated_path:
        return JSONResponse({"error": "Invalid or non-existent file path"}, status_code=404)

    existing = store.get_active_knowledge_conversation(file_path, user_id=user_email)
    if existing:
        return {
            "id": existing.id,
            "resumed": True,
            "staged_files": list_staged_files(existing.id),
            "links": {
                "self": f"/api/conversations/{existing.id}",
                "stream": f"/api/conversations/{existing.id}/stream",
                "commit": f"/api/knowledge/conversations/{existing.id}/commit",
                "abandon": f"/api/knowledge/conversations/{existing.id}/abandon",
            },
        }

    conv = store.create_conversation(conv_type="knowledge", file_path=file_path, user_id=user_email)

    staging_dir = get_staging_dir(conv.id)
    staging_dir.mkdir(parents=True, exist_ok=True)

    staged_file = (staging_dir / file_path).resolve()
    if not str(staged_file).startswith(str(staging_dir.resolve())):
        return JSONResponse({"error": "Invalid path"}, status_code=400)
    staged_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(validated_path, staged_file)

    return {
        "id": conv.id,
        "resumed": False,
        "staged_files": [file_path],
        "links": {
            "self": f"/api/conversations/{conv.id}",
            "stream": f"/api/conversations/{conv.id}/stream",
            "commit": f"/api/knowledge/conversations/{conv.id}/commit",
            "abandon": f"/api/knowledge/conversations/{conv.id}/abandon",
        },
    }


@router.get("/conversations/{conv_id}/files")
def get_staged_files(conv_id: str):
    conv = store.get_conversation(conv_id, include_messages=True)
    if not conv or conv.conv_type != "knowledge":
        return JSONResponse({"error": "Knowledge conversation not found"}, status_code=404)

    first_user_message = None
    for msg in conv.messages:
        if msg.type == "user":
            first_user_message = msg.content[:200]
            break

    return {
        "files": list_staged_files(conv_id),
        "conversation_id": conv_id,
        "first_user_message": first_user_message,
    }


@router.post("/conversations/{conv_id}/commit")
async def commit_knowledge_changes(conv_id: str, request: Request):
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return JSONResponse({"error": "Knowledge conversation not found"}, status_code=404)

    if conv.status != "active":
        return JSONResponse({"error": "Conversation is not active"}, status_code=400)

    staging_dir = get_staging_dir(conv_id)
    if not staging_dir.exists():
        return JSONResponse({"error": "No staged files"}, status_code=400)

    staged_files = list_staged_files(conv_id)
    if not staged_files:
        return JSONResponse({"error": "No staged files"}, status_code=400)

    body = await request.body()
    data = (await request.json()) if body else {}
    summary = data.get("summary", "Knowledge update")

    # Collect file contents
    files = {}
    for rel_path in staged_files:
        src = (staging_dir / rel_path).resolve()
        if not str(src).startswith(str(staging_dir.resolve())) or not src.exists():
            continue
        # Path in repo includes knowledge/ prefix
        repo_path = f"knowledge/{rel_path}"
        files[repo_path] = src.read_text()

    # Create GitHub PR
    try:
        github = GitHubClient()
        pr_url = github.create_knowledge_pr(
            files=files,
            summary=summary,
            conversation_id=conv_id,
        )
    except GitHubError as e:
        logger.error("GitHub PR creation failed: %s", e)
        return JSONResponse({"error": "GitHub PR creation failed"}, status_code=500)

    # Clean up staging
    shutil.rmtree(staging_dir, ignore_errors=True)
    store.update_conversation(conv_id, status="committed", pr_url=pr_url)

    # Add system message to conversation with PR link
    store.add_message(
        conv_id,
        type="system",
        content=f"Changes submitted as pull request: {pr_url}",
    )

    return {
        "status": "committed",
        "files": list(files.keys()),
        "conversation_id": conv_id,
        "pr_url": pr_url,
    }


@router.post("/conversations/{conv_id}/abandon")
def abandon_knowledge_changes(conv_id: str):
    """Abandon staged changes and close conversation."""
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return JSONResponse({"error": "Knowledge conversation not found"}, status_code=404)

    if conv.status != "active":
        return JSONResponse({"error": "Conversation is not active"}, status_code=400)

    staging_dir = get_staging_dir(conv_id)
    shutil.rmtree(staging_dir, ignore_errors=True)
    store.update_conversation(conv_id, status="abandoned")

    return {
        "status": "abandoned",
        "conversation_id": conv_id,
    }


@router.get("/conversations/{conv_id}/preview/{file_path:path}")
def preview_staged_file(conv_id: str, file_path: str):
    """Preview a staged file as rendered HTML."""
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return HTMLResponse("Knowledge conversation not found", status_code=404)

    staging_dir = get_staging_dir(conv_id)
    staged_file = (staging_dir / file_path).resolve()
    if not str(staged_file).startswith(str(staging_dir.resolve())):
        return HTMLResponse("Invalid path", status_code=400)

    if not staged_file.exists():
        return HTMLResponse("Staged file not found", status_code=404)

    content = staged_file.read_text()
    html_content = markdown.markdown(content, extensions=["fenced_code", "tables", "toc"])

    safe_file_path = html_mod.escape(file_path)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <title>Apercu: {safe_file_path}</title>
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
        <small class="text-muted">{safe_file_path}</small>
    </nav>
    <article class="markdown-body">
        {html_content}
    </article>
</body>
</html>""")
