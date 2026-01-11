"""Knowledge API routes."""

import shutil

import markdown
from flask import Blueprint, g, jsonify, request

from ..storage import store
from ..helpers import (
    validate_knowledge_path,
    list_knowledge_files,
    get_staging_dir,
    list_staged_files,
)
from ..github import GitHubClient, GitHubError

bp = Blueprint("knowledge", __name__, url_prefix="/api/knowledge")


@bp.route("", methods=["GET"])
def list_knowledge():
    """List all knowledge files."""
    categories = list_knowledge_files()
    return jsonify({"categories": categories})


@bp.route("/files/<path:file_path>", methods=["GET"])
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


@bp.route("/files/<path:file_path>/conversation", methods=["POST"])
def start_knowledge_conversation(file_path: str):
    """Start or resume a knowledge editing conversation."""
    validated_path = validate_knowledge_path(file_path)
    if not validated_path:
        return jsonify({"error": "Invalid or non-existent file path"}), 404

    existing = store.get_active_knowledge_conversation(file_path, user_id=g.user_email)
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

    conv = store.create_conversation(conv_type="knowledge", file_path=file_path, user_id=g.user_email)

    staging_dir = get_staging_dir(conv.id)
    staging_dir.mkdir(parents=True, exist_ok=True)

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


@bp.route("/conversations/<conv_id>/files", methods=["GET"])
def get_staged_files(conv_id: str):
    """Get list of staged files for a knowledge conversation."""
    conv = store.get_conversation(conv_id, include_messages=True)
    if not conv or conv.conv_type != "knowledge":
        return jsonify({"error": "Knowledge conversation not found"}), 404

    first_user_message = None
    for msg in conv.messages:
        if msg.type == "user":
            first_user_message = msg.content[:200]
            break

    return jsonify({
        "files": list_staged_files(conv_id),
        "conversation_id": conv_id,
        "first_user_message": first_user_message,
    })


@bp.route("/conversations/<conv_id>/commit", methods=["POST"])
def commit_knowledge_changes(conv_id: str):
    """Create GitHub PR with staged changes."""
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

    data = request.get_json() or {}
    summary = data.get("summary", "Knowledge update")

    # Collect file contents
    files = {}
    for rel_path in staged_files:
        src = staging_dir / rel_path
        if src.exists():
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
        return jsonify({"error": f"GitHub PR creation failed: {e}"}), 500

    # Clean up staging
    shutil.rmtree(staging_dir, ignore_errors=True)
    store.update_conversation(conv_id, status="committed", pr_url=pr_url)

    # Add system message to conversation with PR link
    store.add_message(
        conv_id,
        type="system",
        content=f"Changes submitted as pull request: {pr_url}",
    )

    return jsonify({
        "status": "committed",
        "files": list(files.keys()),
        "conversation_id": conv_id,
        "pr_url": pr_url,
    })


@bp.route("/conversations/<conv_id>/abandon", methods=["POST"])
def abandon_knowledge_changes(conv_id: str):
    """Abandon staged changes and close conversation."""
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return jsonify({"error": "Knowledge conversation not found"}), 404

    if conv.status != "active":
        return jsonify({"error": "Conversation is not active"}), 400

    staging_dir = get_staging_dir(conv_id)
    shutil.rmtree(staging_dir, ignore_errors=True)
    store.update_conversation(conv_id, status="abandoned")

    return jsonify({
        "status": "abandoned",
        "conversation_id": conv_id,
    })


@bp.route("/conversations/<conv_id>/preview/<path:file_path>")
def preview_staged_file(conv_id: str, file_path: str):
    """Preview a staged file as rendered HTML."""
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return "Knowledge conversation not found", 404

    staging_dir = get_staging_dir(conv_id)
    staged_file = staging_dir / file_path

    if not staged_file.exists():
        return "Staged file not found", 404

    content = staged_file.read_text()
    html_content = markdown.markdown(content, extensions=["fenced_code", "tables", "toc"])

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="utf-8">
    <title>Apercu: {file_path}</title>
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
