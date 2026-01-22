"""HTML page routes."""

import re
from datetime import datetime, timedelta
from collections import OrderedDict

from flask import Blueprint, render_template, request, g, redirect, abort

from ..config import FEATURE_KNOWLEDGE_CHAT, ADMIN_USERS
from ..storage import store
from ..helpers import validate_knowledge_path, list_knowledge_files, list_staged_files
from .conversations import get_agent_instance

bp = Blueprint("html", __name__)


def humanize_title(title: str) -> str:
    """Clean up a title: strip date prefix, ISO timestamps, separators; capitalize."""
    if not title:
        return title
    title = re.sub(r"^\d{4}-\d{2}(-\d{2})?[-_]?", "", title)
    title = re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?", "", title)
    title = re.sub(r"[-_]+", " ", title)
    if title:
        title = title[0].upper() + title[1:]
    return title.strip()


def format_relative_date(dt):
    """Format a datetime as a relative date string.

    - If today: just time → "14:32"
    - If yesterday: → "hier, 12:45"
    - If this week (not today/yesterday): → "mercredi 11:11"
    - If older: → "23/01/2026 à 22:00"
    """
    now = datetime.now()
    today = now.date()
    dt_date = dt.date()

    day_names = {
        0: "lundi", 1: "mardi", 2: "mercredi", 3: "jeudi",
        4: "vendredi", 5: "samedi", 6: "dimanche"
    }

    # Calculate start of this week (Monday)
    days_since_monday = today.weekday()
    this_week_start = today - timedelta(days=days_since_monday)

    if dt_date == today:
        # Today: just time
        return dt.strftime("%H:%M")
    elif dt_date == today - timedelta(days=1):
        # Yesterday
        return f"hier, {dt.strftime('%H:%M')}"
    elif this_week_start <= dt_date < today:
        # Earlier this week
        day_name = day_names[dt_date.weekday()]
        return f"{day_name} {dt.strftime('%H:%M')}"
    else:
        # Older: full date with time
        return dt.strftime("%d/%m/%Y à %H:%M")


def group_conversations_by_date(conversations):
    """Group conversations by relative date periods.

    Returns OrderedDict with keys like 'aujourd'hui', 'hier', etc.
    and values as lists of conversations.
    """
    now = datetime.now()
    today = now.date()

    groups = OrderedDict()
    groups["aujourd'hui"] = []
    groups["hier"] = []
    groups["plus tôt cette semaine"] = []
    groups["la semaine dernière"] = []
    groups["plus tôt ce mois-ci"] = []

    # Calculate date boundaries
    yesterday = today - timedelta(days=1)

    # Start of this week (Monday)
    days_since_monday = today.weekday()
    this_week_start = today - timedelta(days=days_since_monday)

    # Last week boundaries
    last_week_start = this_week_start - timedelta(days=7)
    last_week_end = this_week_start - timedelta(days=1)

    # Start of this month
    this_month_start = today.replace(day=1)

    # Track which months we've seen for older conversations
    month_names = {
        1: "janvier", 2: "février", 3: "mars", 4: "avril",
        5: "mai", 6: "juin", 7: "juillet", 8: "août",
        9: "septembre", 10: "octobre", 11: "novembre", 12: "décembre"
    }

    for conv in conversations:
        conv_date = conv.updated_at.date()

        if conv_date == today:
            groups["aujourd'hui"].append(conv)
        elif conv_date == yesterday:
            groups["hier"].append(conv)
        elif this_week_start <= conv_date < today:
            groups["plus tôt cette semaine"].append(conv)
        elif last_week_start <= conv_date <= last_week_end:
            groups["la semaine dernière"].append(conv)
        elif this_month_start <= conv_date < this_week_start:
            groups["plus tôt ce mois-ci"].append(conv)
        else:
            # Older conversations - group by month name
            month_key = month_names[conv_date.month]
            if conv_date.year < today.year:
                month_key = f"{month_key} {conv_date.year}"

            if month_key not in groups:
                groups[month_key] = []
            groups[month_key].append(conv)

    # Remove empty groups
    return OrderedDict((k, v) for k, v in groups.items() if v)


def get_sidebar_data():
    """Get data for sidebar (recent conversations for current user)."""
    user_email = getattr(g, "user_email", None)
    conversations = store.list_conversations(limit=20, user_id=user_email)
    agent = get_agent_instance()

    running_ids = []
    for conv in conversations:
        if conv.title:
            conv.title = humanize_title(conv.title)
        conv.is_running = agent.is_running(conv.id)
        if conv.is_running:
            running_ids.append(conv.id)

        # Get tags and determine icon
        tags = store.get_conversation_tags(conv.id)
        conv.icon = "ri-chat-3-fill"  # Default
        for tag in tags:
            if tag.name == "extraction":
                conv.icon = "ri-table-fill"
                break
            elif tag.name == "meta":
                conv.icon = "ri-settings-3-fill"
                break
            elif tag.name == "appli":
                conv.icon = "ri-window-fill"
                break
            elif tag.name == "analyse":
                conv.icon = "ri-chat-3-fill"
                break

    return {
        "conversations": conversations,
        "running_ids": running_ids,
        "is_admin": user_email in ADMIN_USERS,
        "user_email": user_email,
    }


@bp.route("/")
def index():
    """Redirect to new conversation."""
    return redirect("/explorations/new")


@bp.route("/explorations")
def explorations():
    """Explorations section - conversation list with optional filtering."""
    # Redirect old query param format to new path format
    if conv_id := request.args.get("conv"):
        return redirect(f"/explorations/{conv_id}", code=301)

    user_email = getattr(g, "user_email", None)
    agent = get_agent_instance()

    # Filter params
    mine_only = request.args.get("mine") == "1"
    tag_params = request.args.getlist("tag")

    # Get conversations with tags
    filter_user = user_email if mine_only else None
    conversations_with_tags = store.list_conversations_with_tags(
        user_id=filter_user,
        tag_names=tag_params if tag_params else None,
        limit=100,
    )

    # Add runtime info and formatting
    conversations = []
    for conv, tags in conversations_with_tags:
        if conv.title:
            conv.title = humanize_title(conv.title)
        conv.is_running = agent.is_running(conv.id)
        conv.tags = tags

        # Add formatted relative date
        conv.formatted_date = format_relative_date(conv.updated_at)

        # Determine icon based on type tag (use filled icons)
        conv.icon = "ri-chat-3-fill"  # Default
        for tag in tags:
            if tag.name == "analyse":
                conv.icon = "ri-chat-3-fill"
                break
            elif tag.name == "meta":
                conv.icon = "ri-settings-3-fill"
                break
            elif tag.name == "appli":
                conv.icon = "ri-window-fill"
                break

        # Check if author is current user
        conv.is_mine = conv.user_id == user_email

        conversations.append(conv)

    # Get tags with counts based on current filters
    all_tags = store.get_used_conversation_tags_by_type(
        active_tag_names=tag_params if tag_params else None,
        user_id=filter_user
    )

    # Group conversations by date
    grouped_conversations = group_conversations_by_date(conversations)

    data = get_sidebar_data()
    return render_template(
        "explorations.html",
        section="explorations",
        current_conv=None,
        all_conversations=conversations,
        grouped_conversations=grouped_conversations,
        all_tags=all_tags,
        active_tags=tag_params,
        mine_only=mine_only,
        **data
    )


@bp.route("/explorations/new")
def explorations_new():
    """Start a new conversation - empty chat UI."""
    data = get_sidebar_data()
    return render_template("explorations.html", section="explorations", current_conv=None, is_new=True, **data)


@bp.route("/explorations/<conv_id>")
def explorations_conversation(conv_id: str):
    """View a specific conversation.

    Allows viewing conversations owned by other users (shared via UUID link).
    The owner's email is shown in the header for shared conversations.
    """
    user_email = getattr(g, "user_email", None)

    # Try to get conversation without user filter (allow shared access)
    current_conv = store.get_conversation(conv_id, include_messages=False)

    if not current_conv:
        # Conversation not found
        return redirect("/explorations")

    # Check if this is a shared conversation (owned by someone else)
    is_shared = current_conv.user_id and current_conv.user_id != user_email
    owner_email = current_conv.user_id if is_shared else None

    if current_conv.title:
        current_conv.title = humanize_title(current_conv.title)

    data = get_sidebar_data()
    return render_template(
        "explorations.html",
        section="explorations",
        current_conv=current_conv,
        is_shared=is_shared,
        owner_email=owner_email,
        **data
    )


@bp.route("/connaissances")
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
        validated_path = validate_knowledge_path(file_param)
        if validated_path:
            current_file = file_param
            file_content = validated_path.read_text()

            if conv_id:
                current_conv = store.get_conversation(conv_id, include_messages=False)
            else:
                current_conv = store.get_active_knowledge_conversation(file_param)

            if current_conv:
                staged_files = list_staged_files(current_conv.id)
        else:
            return render_template(
                "connaissances.html",
                section="connaissances",
                error="Fichier non trouve",
                categories=list_knowledge_files(),
                active_conversations=store.list_active_knowledge_conversations(),
                feature_knowledge_chat=FEATURE_KNOWLEDGE_CHAT,
                **data
            )

    categories = list_knowledge_files()
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
        feature_knowledge_chat=FEATURE_KNOWLEDGE_CHAT,
        **data
    )


def is_admin() -> bool:
    """Check if current user is an admin."""
    user_email = getattr(g, "user_email", None)
    return user_email in ADMIN_USERS
