# Reports Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make Reports a first-class section separate from Conversations, with proper linking between the two.

**Architecture:** Reports become standalone entities with their own content storage. Conversations can reference reports via "report" type messages that act as cards/links. The Rapports section gets its own sidebar entry and page with the same chat interface as Explorations.

**Tech Stack:** Flask, SQLite, Jinja2, htmx

---

## Current Problems

1. Reports are created automatically when assistant messages start with YAML front-matter
2. Reports appear as conversations in the sidebar (confusing)
3. No dedicated Reports section in the UI
4. Report content is stored in messages table, not reports table
5. No link cards between conversations and reports

## New Architecture

```
Sidebar:
  - Rapports (NEW - first position)
  - Explorations
  - Connaissances

Reports Table:
  - id, title, website, category, tags
  - content (NEW - stores the actual report markdown)
  - source_conversation_id (NEW - optional link to originating conversation)
  - user_id, created_at, updated_at

Conversations:
  - Normal chat flow
  - "report" type messages act as link cards to reports

Flow:
  1. User asks question in Explorations
  2. Agent produces answer
  3. User (or agent via save_report skill) explicitly saves as report
  4. Report created in reports table with content
  5. "report" message added to conversation linking to the report
```

---

### Task 1: Database Migration - Add content column to reports

**Files:**
- Modify: `web/database.py`

**Step 1: Add migration to v4**

Add after `_migrate_to_v3`:

```python
def _migrate_to_v4(conn: sqlite3.Connection):
    """Migrate to v4: add content to reports, source_conversation_id."""
    cursor = conn.execute("PRAGMA table_info(reports)")
    columns = {row["name"] for row in cursor.fetchall()}

    if "content" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN content TEXT")

    if "source_conversation_id" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN source_conversation_id TEXT")

    # Remove message_id foreign key dependency (keep column for migration)
    # Future: DROP message_id after data migrated

    conn.execute("UPDATE schema_version SET version = 4")
```

**Step 2: Update init_db to call v4 migration**

```python
def init_db():
    with get_db() as conn:
        current_version = get_schema_version(conn)
        if current_version < 1:
            _create_schema_v1(conn)
        if current_version < 2:
            _migrate_to_v2(conn)
        if current_version < 3:
            _migrate_to_v3(conn)
        if current_version < 4:
            _migrate_to_v4(conn)
```

**Step 3: Update SCHEMA_VERSION constant**

```python
SCHEMA_VERSION = 4
```

**Step 4: Commit**

```bash
git add web/database.py
git commit -m "db: add content column to reports table (schema v4)"
```

---

### Task 2: Update Report dataclass and store methods

**Files:**
- Modify: `web/database.py`

**Step 1: Update Report dataclass**

```python
@dataclass
class Report:
    """A report with its content."""
    id: Optional[int] = None
    title: str = ""
    content: Optional[str] = None  # NEW: the actual report markdown
    website: Optional[str] = None
    category: Optional[str] = None
    tags: list[str] = field(default_factory=list)
    original_query: Optional[str] = None
    source_conversation_id: Optional[str] = None  # NEW: where it came from
    user_id: Optional[str] = None
    version: int = 1
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    # Deprecated - keep for backwards compat during migration
    conversation_id: Optional[str] = None
    message_id: Optional[int] = None
```

**Step 2: Update create_report method**

```python
def create_report(
    self,
    title: str,
    content: str,
    website: Optional[str] = None,
    category: Optional[str] = None,
    tags: Optional[list[str]] = None,
    original_query: Optional[str] = None,
    source_conversation_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Report]:
    """Create a report with content."""
    report = Report(
        title=title,
        content=content,
        website=website,
        category=category,
        tags=tags or [],
        original_query=original_query,
        source_conversation_id=source_conversation_id,
        user_id=user_id,
    )

    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO reports
               (title, content, website, category, tags, original_query,
                source_conversation_id, user_id, version, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (title, content, website, category,
             json.dumps(tags) if tags else None, original_query,
             source_conversation_id, user_id,
             1, report.created_at.isoformat(), report.updated_at.isoformat())
        )
        report.id = cursor.lastrowid

    return report
```

**Step 3: Update get_report to use content column**

```python
def get_report(self, report_id: int) -> Optional[Report]:
    """Get a report by ID."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM reports WHERE id = ?", (report_id,)
        ).fetchone()

        if not row:
            return None

        # Use content column if available, fall back to message lookup
        content = row["content"]
        if not content and row["message_id"]:
            # Legacy: fetch from messages
            msg = conn.execute(
                "SELECT content FROM messages WHERE id = ?",
                (row["message_id"],)
            ).fetchone()
            content = msg["content"] if msg else None

        return Report(
            id=row["id"],
            title=row["title"],
            content=content,
            website=row["website"],
            category=row["category"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            original_query=row["original_query"],
            source_conversation_id=row["source_conversation_id"] if "source_conversation_id" in row.keys() else None,
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            # Legacy fields
            conversation_id=row["conversation_id"],
            message_id=row["message_id"],
        )
```

**Step 4: Commit**

```bash
git add web/database.py
git commit -m "db: update Report model to store content directly"
```

---

### Task 3: Remove auto-report creation from streaming

**Files:**
- Modify: `web/routes/conversations.py`

**Step 1: Remove _maybe_create_report function and its call**

Delete the `_maybe_create_report` function (lines ~380-410).

Remove the call in `generate()`:
```python
# DELETE these lines:
if assistant_text_parts and assistant_msg_id:
    full_response = "\n".join(assistant_text_parts)
    if full_response.startswith("---\n"):
        _maybe_create_report(conv_id, assistant_msg_id, full_response, last_message)
```

**Step 2: Commit**

```bash
git add web/routes/conversations.py
git commit -m "remove auto-report creation from YAML front-matter"
```

---

### Task 4: Create Rapports HTML template

**Files:**
- Create: `web/templates/rapports.html`

**Step 1: Create the template**

```html
{% extends "base.html" %}

{% block title_suffix %} - Rapports{% endblock %}

{% block content %}
<section class="section-content" id="section-rapports">
  <!-- Sticky section header -->
  <div class="section-header">
    <div class="container">
      <div class="d-flex align-items-center justify-content-between gap-3">
        <div class="d-flex align-items-center gap-3">
          {% if current_report %}
          <a href="/rapports" class="btn btn-link p-0 me-2" hx-get="/rapports" hx-target="#main" hx-select="#main > *" hx-push-url="true">
            <i class="ri-arrow-left-line ri-xl"></i>
          </a>
          {% endif %}
          <i class="ri-file-text-line ri-2x text-primary"></i>
          <div>
            <h1 class="mb-0">{% if current_report %}{{ current_report.title }}{% else %}Rapports{% endif %}</h1>
            <p class="text-muted mb-0">{% if current_report %}{{ current_report.website or '' }} - {{ current_report.category or '' }}{% else %}Analyses et rapports sauvegardés{% endif %}</p>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Main content area -->
  <div class="container section-body">
    {% if current_report %}
    <!-- Report detail view -->
    <div class="report-content" id="reportContent">
      <div class="card">
        <div class="card-body">
          <div class="report-markdown" id="reportMarkdown">{{ current_report.content }}</div>
        </div>
        <div class="card-footer text-muted small">
          {% if current_report.source_conversation_id %}
          <a href="/explorations?conv={{ current_report.source_conversation_id }}">Voir la conversation d'origine</a> |
          {% endif %}
          Mis à jour le {{ current_report.updated_at.strftime('%d/%m/%Y %H:%M') }}
        </div>
      </div>
    </div>
    {% else %}
    <!-- Reports list view -->
    <div class="reports-list" id="reportsList">
      {% if reports %}
      <div class="row g-3">
        {% for report in reports %}
        <div class="col-12 col-md-6 col-lg-4" id="report-{{ report.id }}">
          <div class="card report-card h-100">
            <a href="/rapports?id={{ report.id }}" class="card-body text-decoration-none"
               hx-get="/rapports?id={{ report.id }}" hx-target="#main" hx-select="#main > *" hx-push-url="true">
              <h5 class="card-title mb-2">{{ report.title }}</h5>
              <p class="card-text text-muted small mb-0">
                {% if report.website %}<span class="badge bg-secondary">{{ report.website }}</span>{% endif %}
                {% if report.category %}<span class="badge bg-light text-dark">{{ report.category }}</span>{% endif %}
              </p>
              <p class="card-text text-muted small mb-0 mt-2">
                {{ report.updated_at.strftime('%d/%m/%Y %H:%M') }}
              </p>
            </a>
            <div class="card-footer-row">
              <div></div>
              <button class="btn btn-link btn-sm text-muted card-delete-btn" title="Supprimer"
                      hx-delete="/api/reports/{{ report.id }}"
                      hx-target="#report-{{ report.id }}"
                      hx-swap="outerHTML"
                      hx-confirm="Supprimer ce rapport ?">
                <i class="ri-delete-bin-line"></i>
              </button>
            </div>
          </div>
        </div>
        {% endfor %}
      </div>
      {% else %}
      <div class="empty-state">
        <i class="ri-file-text-line ri-4x text-disabled mb-3"></i>
        <p class="mb-0 text-muted">Aucun rapport</p>
        <p class="small text-muted">Demandez a l'agent de sauvegarder un rapport</p>
      </div>
      {% endif %}
    </div>
    {% endif %}
  </div>

  <!-- Fixed chat bar at bottom -->
  <div class="chat-bar-container">
    <div class="container">
      <div class="chat-bar">
        <textarea
          class="chat-input"
          id="chatInput"
          placeholder="Posez une question pour creer une nouvelle exploration..."
          rows="1"
        ></textarea>
        <button type="button" class="chat-send-btn" id="chatSendBtn" title="Envoyer">
          <i class="ri-send-plane-fill"></i>
        </button>
      </div>
    </div>
  </div>
</section>
{% endblock %}

{% block scripts %}
<script>
document.addEventListener('DOMContentLoaded', () => {
  // Render markdown in report content
  const reportMarkdown = document.getElementById('reportMarkdown');
  if (reportMarkdown && typeof marked !== 'undefined') {
    reportMarkdown.innerHTML = marked.parse(reportMarkdown.textContent);
    // Render mermaid diagrams
    if (typeof mermaid !== 'undefined') {
      mermaid.run({ nodes: reportMarkdown.querySelectorAll('.language-mermaid') });
    }
  }

  // Chat bar creates new exploration
  const chatInput = document.getElementById('chatInput');
  const chatSendBtn = document.getElementById('chatSendBtn');

  if (chatInput && chatSendBtn) {
    chatSendBtn.addEventListener('click', async () => {
      const message = chatInput.value.trim();
      if (!message) return;

      // Create new conversation and redirect to explorations with message
      const resp = await fetch('/api/conversations', { method: 'POST' });
      const data = await resp.json();
      window.location.href = `/explorations?conv=${data.id}&message=${encodeURIComponent(message)}`;
    });

    chatInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        chatSendBtn.click();
      }
    });
  }
});
</script>
{% endblock %}
```

**Step 2: Commit**

```bash
git add web/templates/rapports.html
git commit -m "ui: add Rapports template"
```

---

### Task 5: Add Rapports route

**Files:**
- Create: `web/routes/rapports.py`
- Modify: `web/routes/__init__.py`
- Modify: `web/app.py`

**Step 1: Create rapports.py**

```python
"""Rapports HTML routes."""

from flask import Blueprint, render_template, request

from ..storage import store
from .html import get_sidebar_data

bp = Blueprint("rapports", __name__)


@bp.route("/rapports")
def rapports():
    """Rapports section - saved reports browser."""
    data = get_sidebar_data()
    report_id = request.args.get("id", type=int)

    current_report = None
    if report_id:
        current_report = store.get_report(report_id)

    reports = store.list_reports(limit=50) if not current_report else []

    return render_template(
        "rapports.html",
        section="rapports",
        current_report=current_report,
        reports=reports,
        **data
    )
```

**Step 2: Update routes/__init__.py**

```python
from .rapports import bp as rapports_bp

__all__ = [
    "conversations_bp",
    "reports_bp",
    "knowledge_bp",
    "logs_bp",
    "html_bp",
    "rapports_bp",  # NEW
]
```

**Step 3: Register blueprint in app.py**

```python
from .routes import (
    conversations_bp,
    reports_bp,
    knowledge_bp,
    logs_bp,
    html_bp,
    rapports_bp,  # NEW
)

# ... in blueprints section:
app.register_blueprint(rapports_bp)
```

**Step 4: Commit**

```bash
git add web/routes/rapports.py web/routes/__init__.py web/app.py
git commit -m "routes: add /rapports page"
```

---

### Task 6: Update sidebar - add Rapports as first item

**Files:**
- Modify: `web/templates/base.html`

**Step 1: Add Rapports nav item before Explorations**

In the `<nav class="sidebar-nav">` section, add before Explorations:

```html
<li class="nav-item">
  <a href="/rapports" class="nav-link {% if section == 'rapports' %}active{% endif %}"
     hx-get="/rapports" hx-target="#main" hx-select="#main > *" hx-push-url="true">
    <i class="ri-file-text-line" aria-hidden="true"></i>
    <span>Rapports</span>
  </a>
</li>
```

**Step 2: Add to mobile nav as well**

Same HTML in the offcanvas mobile nav section.

**Step 3: Commit**

```bash
git add web/templates/base.html
git commit -m "ui: add Rapports to sidebar as first item"
```

---

### Task 7: Add DELETE endpoint for reports

**Files:**
- Modify: `web/routes/reports.py`
- Modify: `web/database.py`

**Step 1: Add delete_report to store**

In `database.py`, add to `ConversationStore`:

```python
def delete_report(self, report_id: int) -> bool:
    """Delete a report."""
    with get_db() as conn:
        cursor = conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
        return cursor.rowcount > 0
```

**Step 2: Add DELETE endpoint**

In `routes/reports.py`:

```python
@bp.route("/<int:report_id>", methods=["DELETE"])
def delete_report(report_id: int):
    """Delete a report."""
    if store.delete_report(report_id):
        return "", 200
    return jsonify({"error": "Report not found"}), 404
```

**Step 3: Commit**

```bash
git add web/routes/reports.py web/database.py
git commit -m "api: add DELETE /api/reports/:id endpoint"
```

---

### Task 8: Update save_report skill to use new API

**Files:**
- Modify: `skills/save_report/scripts/save_report.py`
- Modify: `skills/save_report/SKILL.md`

**Step 1: Read current script**

First read the current implementation to understand the interface.

**Step 2: Update to create report with content directly**

The script should:
1. Read the report content from file
2. POST to `/api/reports` with `{title, content, website, category, source_conversation_id}`
3. Optionally add a "report" message to the source conversation

**Step 3: Commit**

```bash
git add skills/save_report/
git commit -m "skill: update save_report for new reports API"
```

---

### Task 9: Add POST endpoint for creating reports

**Files:**
- Modify: `web/routes/reports.py`

**Step 1: Add create report endpoint**

```python
@bp.route("", methods=["POST"])
def create_report():
    """Create a new report."""
    from flask import g

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
```

**Step 2: Add import**

```python
import json
```

**Step 3: Commit**

```bash
git add web/routes/reports.py
git commit -m "api: add POST /api/reports endpoint"
```

---

### Task 10: Deploy and test

**Step 1: Deploy**

```bash
./deploy/deploy.sh
```

**Step 2: Test manually**

1. Visit /rapports - should see empty state or existing reports
2. Create a report via API or save_report skill
3. Report appears in /rapports
4. Click report to view content
5. Chat bar creates new exploration

**Step 3: Final commit if needed**

```bash
git add -A
git commit -m "reports redesign: complete implementation"
```

---

### Task 11: Report-worthy detection and toggle button

**Goal:** Agent infers if question deserves a detailed report. User can toggle report generation on/off.

**Files:**
- Modify: `web/static/js/chat.js`
- Modify: `web/routes/conversations.py`
- Modify: `web/templates/explorations.html` (or base chat CSS)

**Step 1: Add report toggle UI component**

Add a button at bottom of conversation (near chat input):
- When agent idle: Simple button "Produire un rapport détaillé"
- When agent streaming: Button contains checkbox, clicking toggles state
- Hidden by default, shown when agent signals question is report-worthy

```html
<div class="report-toggle" id="reportToggle" style="display: none;">
  <button type="button" class="btn btn-outline-primary btn-sm" id="reportToggleBtn">
    <span class="toggle-idle">Produire un rapport détaillé</span>
    <span class="toggle-streaming" style="display: none;">
      <input type="checkbox" id="reportCheckbox"> Produire un rapport détaillé
    </span>
  </button>
</div>
```

**Step 2: Add SSE event for report-worthy signal**

Agent sends event when it determines question is report-worthy:
```javascript
// In streaming handler
case 'report_worthy':
  document.getElementById('reportToggle').style.display = 'block';
  break;
```

**Step 3: Update agent to detect report-worthy questions**

In the agent system prompt or first-turn logic, detect if question is:
- Analytical (stats, trends, comparisons)
- Requires synthesis of multiple data points
- Explicitly asks for report/analysis

Send `report_worthy` event to frontend.

**Step 4: Handle toggle state and report generation**

When agent finishes streaming:
1. Check if reportCheckbox is checked
2. If yes, call `/api/reports` POST with conversation content
3. Hide the toggle button once report generation starts

**Step 5: Commit**

```bash
git add web/static/js/chat.js web/routes/conversations.py web/templates/explorations.html
git commit -m "ui: add report-worthy detection and toggle button"
```

---

## Tests to Add Later

1. `get_report()` legacy fallback - verify old reports (with message_id, no content) still load correctly
2. `create_report()` - verify new reports store content directly

---

## Future Improvements (Not in this PR)

1. Report versioning - keep history of edits
2. Report search/filter in UI
3. Report export (PDF, markdown download)
4. Report sharing (public links)
5. Render "report" messages as cards in conversation view
