"""Save report skill - create, update, or append reports to the database."""

import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from web.database import ConversationStore


def save_report(
    title: str,
    content: str,
    website: str = None,
    category: str = None,
    original_query: str = None,
    source_conversation_id: str = None,
    tags: list[str] = None,
) -> dict:
    """
    Create a new report.

    Args:
        title: Report title
        content: Report content (markdown)
        website: Website name (emplois, dora, etc.)
        category: Query category
        original_query: Original user question
        source_conversation_id: Optional ID of conversation that generated this report
        tags: List of tag names (e.g. ["emplois", "candidats", "analyse"])

    Returns:
        {"report_id": int, "source_conversation_id": str or None}
    """
    store = ConversationStore()

    # Create report with content stored directly
    report = store.create_report(
        title=title,
        content=content,
        website=website,
        category=category,
        original_query=original_query,
        source_conversation_id=source_conversation_id,
    )

    # Set tags if provided
    if tags:
        store.set_report_tags(report.id, tags, update_timestamp=False)

    # Add link message to source conversation if provided
    if source_conversation_id:
        import json
        store.add_message(
            source_conversation_id,
            "report",
            json.dumps({"report_id": report.id, "title": report.title})
        )

    return {
        "report_id": report.id,
        "source_conversation_id": source_conversation_id,
    }


def update_report(
    report_id: int,
    content: str,
    title: str = None,
    website: str = None,
    category: str = None,
) -> dict:
    """
    Update an existing report's content and metadata.

    Args:
        report_id: ID of the report to update
        content: New report content
        title: New title (optional)
        website: New website (optional)
        category: New category (optional)

    Returns:
        {"report_id": int, "version": int}
    """
    store = ConversationStore()

    # Get the report to verify it exists
    report = store.get_report(report_id)
    if not report:
        raise ValueError(f"Report {report_id} not found")

    # Update report content and metadata
    updates = {"content": content}
    if title:
        updates["title"] = title
    if website:
        updates["website"] = website
    if category:
        updates["category"] = category

    store.update_report(report_id, **updates)

    # Get updated version
    updated_report = store.get_report(report_id)

    return {
        "report_id": report_id,
        "version": updated_report.version,
    }


def append_report(
    conversation_id: str,
    title: str,
    content: str,
    website: str = None,
    category: str = None,
    original_query: str = None,
    tags: list[str] = None,
) -> dict:
    """
    Create a new report linked to an existing conversation.

    Args:
        conversation_id: ID of the source conversation
        title: Report title
        content: Report content
        website: Website name
        category: Query category
        original_query: Original user question
        tags: List of tag names

    Returns:
        {"report_id": int, "source_conversation_id": str}
    """
    # Just delegate to save_report with source_conversation_id
    return save_report(
        title=title,
        content=content,
        website=website,
        category=category,
        original_query=original_query,
        source_conversation_id=conversation_id,
        tags=tags,
    )


def list_reports(website: str = None, category: str = None, limit: int = 20) -> list:
    """
    List existing reports.

    Args:
        website: Filter by website
        category: Filter by category
        limit: Max reports to return

    Returns:
        List of report dicts with id, title, website, category, version
    """
    store = ConversationStore()
    reports = store.list_reports(website=website, category=category, limit=limit)

    return [
        {
            "id": r.id,
            "title": r.title,
            "website": r.website,
            "category": r.category,
            "version": r.version,
            "source_conversation_id": r.source_conversation_id,
        }
        for r in reports
    ]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Save or update reports in the database")
    parser.add_argument("--file", "-f", help="Path to markdown file containing report content")
    parser.add_argument("--title", "-t", help="Report title")
    parser.add_argument("--website", "-w", help="Website (emplois, dora, etc.)")
    parser.add_argument("--category", "-c", help="Query category")
    parser.add_argument("--query", "-q", help="Original user query")
    parser.add_argument("--tags", help="Comma-separated tags (e.g. 'emplois,candidats,analyse')")
    parser.add_argument("--report-id", "-r", type=int, help="Report ID to update (for updates)")
    parser.add_argument("--conversation-id", help="Source conversation ID to link report to")
    parser.add_argument("--list", "-l", action="store_true", help="List recent reports")

    args = parser.parse_args()

    if args.list:
        reports = list_reports(limit=10)
        print("Recent reports:")
        for r in reports:
            print(f"  [{r['id']}] {r['title']} (v{r['version']}) - {r['website'] or 'N/A'}")
        sys.exit(0)

    if not args.file:
        parser.error("--file is required for save/update operations")

    # Read content from file
    content_path = Path(args.file)
    if not content_path.exists():
        print(f"Error: File not found: {args.file}", file=sys.stderr)
        sys.exit(1)
    content = content_path.read_text()

    # Parse tags
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else None

    if args.report_id:
        # Update existing report
        result = update_report(
            report_id=args.report_id,
            content=content,
            title=args.title,
            website=args.website,
            category=args.category,
        )
        print(f"Updated report {result['report_id']} to version {result['version']}")

    elif args.conversation_id:
        # Create report linked to conversation
        if not args.title:
            parser.error("--title is required when linking to conversation")
        result = append_report(
            conversation_id=args.conversation_id,
            title=args.title,
            content=content,
            website=args.website,
            category=args.category,
            original_query=args.query,
            tags=tags,
        )
        print(f"Created report {result['report_id']} linked to conversation {result['source_conversation_id']}")

    else:
        # Create new standalone report
        if not args.title:
            parser.error("--title is required for new reports")
        result = save_report(
            title=args.title,
            content=content,
            website=args.website,
            category=args.category,
            original_query=args.query,
            tags=tags,
        )
        print(f"Created report {result['report_id']}")
