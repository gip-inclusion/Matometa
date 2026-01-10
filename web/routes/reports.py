"""Reports API routes."""

from flask import Blueprint, jsonify, request

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
