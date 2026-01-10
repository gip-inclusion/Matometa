"""Reports API routes."""

import json

from flask import Blueprint, g, jsonify, request

from ..storage import store

bp = Blueprint("reports", __name__, url_prefix="/api/reports")


@bp.route("", methods=["GET"])
def list_reports():
    """List available reports from database."""
    website = request.args.get("website")
    category = request.args.get("category")
    limit = request.args.get("limit", 50, type=int)

    reports = store.list_reports(website=website, category=category, limit=limit)
    return jsonify({
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
    })


@bp.route("/<int:report_id>", methods=["GET"])
def get_report(report_id: int):
    """Get a specific report."""
    report = store.get_report(report_id)
    if not report:
        return jsonify({"error": "Report not found"}), 404

    return jsonify({
        "id": report.id,
        "title": report.title,
        "website": report.website,
        "category": report.category,
        "tags": report.tags,
        "original_query": report.original_query,
        "version": report.version,
        "content": report.content,
        "source_conversation_id": report.source_conversation_id,
        "created_at": report.created_at.isoformat(),
        "updated_at": report.updated_at.isoformat(),
        "links": {
            "self": f"/api/reports/{report.id}",
            "view": f"/rapports?id={report.id}",
        },
    })


@bp.route("/<int:report_id>", methods=["DELETE"])
def delete_report(report_id: int):
    """Delete a report."""
    if store.delete_report(report_id):
        return "", 200
    return jsonify({"error": "Report not found"}), 404


@bp.route("", methods=["POST"])
def create_report():
    """Create a new report."""
    data = request.get_json()
    if not data or "title" not in data or "content" not in data:
        return jsonify({"error": "Missing title or content"}), 400

    user_email = getattr(g, "user_email", None)

    report = store.create_report(
        title=data["title"],
        content=data["content"],
        website=data.get("website"),
        category=data.get("category"),
        tags=data.get("tags"),
        original_query=data.get("original_query"),
        source_conversation_id=data.get("source_conversation_id"),
        user_id=user_email,
    )

    if not report:
        return jsonify({"error": "Failed to create report"}), 500

    # Optionally add link message to source conversation
    if data.get("source_conversation_id"):
        store.add_message(
            data["source_conversation_id"],
            "report",
            json.dumps({"report_id": report.id, "title": report.title})
        )

    return jsonify({
        "id": report.id,
        "title": report.title,
        "links": {
            "self": f"/api/reports/{report.id}",
            "view": f"/rapports?id={report.id}",
        }
    }), 201
