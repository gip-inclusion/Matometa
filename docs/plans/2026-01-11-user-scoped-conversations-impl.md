# User-Scoped Conversations Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make conversations private per user and redesign sidebar to show recent conversations inline.

**Architecture:** Add `DEFAULT_USER` config, filter conversations by `g.user_email`, restructure URL routes (`/explorations/new`, `/explorations/<uuid>`), redesign sidebar with conversation list.

**Tech Stack:** Flask, SQLite, Jinja2, vanilla JavaScript

---

## Task 1: Add DEFAULT_USER Config

**Files:**
- Modify: `web/config.py:1-36`
- Modify: `.env:1-13`

**Step 1: Add DEFAULT_USER to config.py**

Add after line 31 (after `DEBUG = ...`):

```python
# Default user for local development (when oauth-proxy not present)
DEFAULT_USER = os.getenv("DEFAULT_USER", "admin@localhost")
```

**Step 2: Add DEFAULT_USER to .env**

Add at end of file:

```
# User identity (for local dev without oauth-proxy)
DEFAULT_USER=admin@localhost
```

**Step 3: Commit**

```bash
git add web/config.py .env && git commit -m "config: add DEFAULT_USER for local dev identity"
```

---

## Task 2: Update User Identity Resolution

**Files:**
- Modify: `web/app.py:36-48`

**Step 1: Update extract_user_email middleware**

Replace the `extract_user_email` function:

```python
@app.before_request
def extract_user_email():
    """
    Extract authenticated user email from oauth2-proxy headers.
    Falls back to DEFAULT_USER for local development.
    """
    g.user_email = (
        request.headers.get("X-Forwarded-Email")
        or config.DEFAULT_USER
    )
    g.user_name = request.headers.get("X-Forwarded-User")
```

**Step 2: Commit**

```bash
git add web/app.py && git commit -m "auth: fall back to DEFAULT_USER when oauth headers missing"
```

---

## Task 3: Add User Filtering to Database Layer

**Files:**
- Modify: `web/database.py:465-522` (list_conversations)
- Modify: `web/database.py:397-463` (get_conversation)

**Step 1: Update list_conversations to require user_id filter**

The method already has `user_id` parameter at line 466. Verify it's used correctly in the query (lines 476-480). No changes needed to method signature.

**Step 2: Update get_conversation to check user ownership**

Add `user_id` parameter and ownership check. Replace method starting at line 397:

```python
def get_conversation(self, conv_id: str, include_messages: bool = True, user_id: Optional[str] = None) -> Optional[Conversation]:
    """Get a conversation by ID. Optionally filter by user_id for access control."""
    with get_db() as conn:
        if user_id:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ? AND user_id = ?", (conv_id, user_id)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()

        if not row:
            return None
        # ... rest of method unchanged
```

**Step 3: Commit**

```bash
git add web/database.py && git commit -m "db: add user_id filtering to get_conversation"
```

---

## Task 4: Update API Routes to Filter by User

**Files:**
- Modify: `web/routes/conversations.py:79-97` (list_conversations)
- Modify: `web/routes/conversations.py:100-116` (get_conversation)

**Step 1: Update list_conversations route**

Replace line 83:

```python
convs = store.list_conversations(limit=limit, user_id=g.user_email)
```

**Step 2: Update get_conversation route**

Replace line 103:

```python
conv = store.get_conversation(conv_id, user_id=g.user_email)
```

**Step 3: Update stream_conversation route**

At line 237, add user check:

```python
conv = store.get_conversation(conv_id, user_id=g.user_email)
```

**Step 4: Commit**

```bash
git add web/routes/conversations.py && git commit -m "api: filter conversations by current user"
```

---

## Task 5: Update HTML Routes - Sidebar Data

**Files:**
- Modify: `web/routes/html.py:26-39` (get_sidebar_data)

**Step 1: Import g from flask**

Line 5 already imports from flask. Verify `g` is imported. If not, update:

```python
from flask import Blueprint, render_template, request, g
```

**Step 2: Update get_sidebar_data to filter by user**

Replace the function:

```python
def get_sidebar_data():
    """Get data for sidebar (recent conversations for current user)."""
    user_email = getattr(g, "user_email", None)
    conversations = store.list_conversations(limit=15, user_id=user_email)
    agent = get_agent_instance()

    running_ids = []
    for conv in conversations:
        if conv.title:
            conv.title = humanize_title(conv.title)
        conv.is_running = agent.is_running(conv.id)
        if conv.is_running:
            running_ids.append(conv.id)

    return {"conversations": conversations, "running_ids": running_ids}
```

**Step 3: Commit**

```bash
git add web/routes/html.py && git commit -m "html: filter sidebar conversations by current user"
```

---

## Task 6: Add New URL Routes

**Files:**
- Modify: `web/routes/html.py:42-59`

**Step 1: Update explorations route with redirect and new patterns**

Replace the explorations route and add new routes:

```python
@bp.route("/explorations")
def explorations():
    """Explorations section - conversation list or redirect from old URL."""
    # Redirect old query param format to new path format
    if conv_id := request.args.get("conv"):
        return redirect(f"/explorations/{conv_id}", code=301)

    data = get_sidebar_data()
    return render_template("explorations.html", section="explorations", current_conv=None, **data)


@bp.route("/explorations/new")
def explorations_new():
    """Start a new conversation - empty chat UI."""
    data = get_sidebar_data()
    return render_template("explorations.html", section="explorations", current_conv=None, is_new=True, **data)


@bp.route("/explorations/<conv_id>")
def explorations_conversation(conv_id: str):
    """View a specific conversation."""
    user_email = getattr(g, "user_email", None)
    current_conv = store.get_conversation(conv_id, include_messages=False, user_id=user_email)

    if not current_conv:
        # Conversation not found or not owned by user
        return redirect("/explorations")

    if current_conv.title:
        current_conv.title = humanize_title(current_conv.title)

    data = get_sidebar_data()
    return render_template("explorations.html", section="explorations", current_conv=current_conv, **data)
```

**Step 2: Add redirect import**

Update line 5:

```python
from flask import Blueprint, render_template, request, g, redirect
```

**Step 3: Commit**

```bash
git add web/routes/html.py && git commit -m "routes: add /explorations/new and /explorations/<uuid> routes"
```

---

## Task 7: Redesign Sidebar Template

**Files:**
- Modify: `web/templates/base.html:40-66`

**Step 1: Replace sidebar nav with new structure**

Replace lines 40-66:

```html
    <nav class="sidebar-nav" role="navigation" id="nav-primary" aria-label="Navigation principale">
      <ul class="nav flex-column">
        <li class="nav-item">
          <a href="/explorations/new" class="nav-link nav-link-primary {% if section == 'explorations' and not current_conv %}active{% endif %}"
             hx-get="/explorations/new" hx-target="#main" hx-select="#main > *" hx-push-url="true">
            <i class="ri-add-line" aria-hidden="true"></i>
            <span>Nouvelle conversation</span>
          </a>
        </li>

        <li class="nav-item">
          <a href="/rapports" class="nav-link {% if section == 'rapports' %}active{% endif %}"
             hx-get="/rapports" hx-target="#main" hx-select="#main > *" hx-push-url="true">
            <i class="ri-file-text-line" aria-hidden="true"></i>
            <span>Rapports</span>
          </a>
        </li>

        <li class="nav-item">
          <a href="/connaissances" class="nav-link {% if section == 'connaissances' %}active{% endif %}"
             hx-get="/connaissances" hx-target="#main" hx-select="#main > *" hx-push-url="true">
            <i class="ri-book-open-line" aria-hidden="true"></i>
            <span>Connaissances</span>
          </a>
        </li>
      </ul>

      <!-- Recent conversations -->
      {% if conversations %}
      <div class="sidebar-conversations">
        <ul class="nav flex-column">
          {% for conv in conversations[:15] %}
          <li class="nav-item">
            <a href="/explorations/{{ conv.id }}"
               class="nav-link nav-link-conversation {% if current_conv and current_conv.id == conv.id %}active{% endif %}"
               hx-get="/explorations/{{ conv.id }}" hx-target="#main" hx-select="#main > *" hx-push-url="true"
               title="{{ conv.title or 'Sans titre' }}">
              {% if conv.is_running %}<i class="ri-loader-4-line ri-spin" aria-hidden="true"></i>{% endif %}
              <span class="conv-title-text">{{ conv.title or 'Sans titre' }}</span>
            </a>
          </li>
          {% endfor %}
        </ul>
        <a href="/explorations" class="sidebar-view-more"
           hx-get="/explorations" hx-target="#main" hx-select="#main > *" hx-push-url="true">
          Voir plus...
        </a>
      </div>
      {% endif %}
    </nav>
```

**Step 2: Commit**

```bash
git add web/templates/base.html && git commit -m "template: redesign sidebar with conversation list"
```

---

## Task 8: Update Mobile Offcanvas Menu

**Files:**
- Modify: `web/templates/base.html:88-107`

**Step 1: Update mobile nav to match new sidebar structure**

Replace lines 88-107:

```html
      <nav role="navigation">
        <ul class="nav flex-column">
          <li class="nav-item">
            <a href="/explorations/new" class="nav-link {% if section == 'explorations' and not current_conv %}active{% endif %}">
              <i class="ri-add-line me-2"></i>Nouvelle conversation
            </a>
          </li>
          <li class="nav-item">
            <a href="/rapports" class="nav-link {% if section == 'rapports' %}active{% endif %}">
              <i class="ri-file-text-line me-2"></i>Rapports
            </a>
          </li>
          <li class="nav-item">
            <a href="/connaissances" class="nav-link {% if section == 'connaissances' %}active{% endif %}">
              <i class="ri-book-open-line me-2"></i>Connaissances
            </a>
          </li>
        </ul>
        {% if conversations %}
        <hr class="my-2">
        <ul class="nav flex-column">
          {% for conv in conversations[:10] %}
          <li class="nav-item">
            <a href="/explorations/{{ conv.id }}" class="nav-link nav-link-conversation {% if current_conv and current_conv.id == conv.id %}active{% endif %}">
              {{ conv.title or 'Sans titre' }}
            </a>
          </li>
          {% endfor %}
          <li class="nav-item">
            <a href="/explorations" class="nav-link text-muted small">Voir plus...</a>
          </li>
        </ul>
        {% endif %}
      </nav>
```

**Step 2: Commit**

```bash
git add web/templates/base.html && git commit -m "template: update mobile nav with conversation list"
```

---

## Task 9: Add Sidebar Conversation Styles

**Files:**
- Modify: `web/static/css/style.css` (append to end)

**Step 1: Add styles for conversation list in sidebar**

Append to end of file:

```css
/* Sidebar conversation list */
.sidebar-conversations {
  margin-top: 1rem;
  padding-top: 1rem;
  border-top: 1px solid rgba(0, 0, 0, 0.1);
  max-height: calc(100vh - 300px);
  overflow-y: auto;
}

.nav-link-conversation {
  font-size: 0.85rem;
  color: var(--bs-secondary);
  padding: 0.35rem 1rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.nav-link-conversation:hover {
  color: var(--bs-primary);
  background-color: rgba(0, 106, 220, 0.05);
}

.nav-link-conversation.active {
  color: var(--bs-primary);
  font-weight: 500;
}

.nav-link-conversation .ri-loader-4-line {
  margin-right: 0.25rem;
}

.conv-title-text {
  overflow: hidden;
  text-overflow: ellipsis;
}

.sidebar-view-more {
  display: block;
  padding: 0.5rem 1rem;
  font-size: 0.8rem;
  color: var(--bs-secondary);
  text-decoration: none;
}

.sidebar-view-more:hover {
  color: var(--bs-primary);
}

.nav-link-primary {
  font-weight: 500;
}
```

**Step 2: Commit**

```bash
git add web/static/css/style.css && git commit -m "styles: add sidebar conversation list styles"
```

---

## Task 10: Update Explorations Template for New Mode

**Files:**
- Modify: `web/templates/explorations.html:85-140`

**Step 1: Update conversation list links to use new URL pattern**

Replace line 100-101 (the card link):

```html
            <a href="/explorations/{{ conv.id }}" class="card-body text-decoration-none"
               hx-get="/explorations/{{ conv.id }}" hx-target="#main" hx-select="#main > *" hx-push-url="true">
```

**Step 2: Update background running alert link (line 73)**

Replace:

```html
        <a href="/explorations/{{ background_running[0] }}" class="alert-link">Voir</a>
```

**Step 3: Update back button link (line 13)**

Replace:

```html
          <a href="/explorations" class="btn btn-link p-0 me-2" hx-get="/explorations" hx-target="#main" hx-select="#main > *" hx-push-url="true">
```

**Step 4: Handle is_new template variable for empty chat focus**

The template already handles `current_conv` being None, which is the "new" case. Add focus hint in scripts block. Update line 167-192:

```html
{% block scripts %}
<script>
  document.addEventListener('DOMContentLoaded', async () => {
    {% if current_conv %}
    // Set conversation ID before initChat to prevent duplicate loadConversation call
    currentConversationId = '{{ current_conv.id }}';
    {% endif %}

    // Initialize chat UI
    initChat();

    {% if current_conv %}
    // Check for pending message BEFORE loadConversation (which modifies URL)
    const pendingMessage = new URLSearchParams(window.location.search).get('message');

    // Load existing conversation
    await loadConversation('{{ current_conv.id }}');

    // Send pending message if any
    if (pendingMessage) {
      appendEvent('user', { content: pendingMessage });
      lastUserMessage = pendingMessage;
      await sendToAgent(pendingMessage);
    }
    {% elif is_new %}
    // New conversation mode - focus input
    const input = document.getElementById('chatInput');
    if (input) input.focus();
    {% endif %}
  });
</script>
{% endblock %}
```

**Step 5: Commit**

```bash
git add web/templates/explorations.html && git commit -m "template: update explorations for new URL structure"
```

---

## Task 11: Update JavaScript for Deferred Conversation Creation

**Files:**
- Modify: `web/static/js/chat.js:277-324` (sendMessage function)
- Modify: `web/static/js/chat.js:1063-1128` (loadConversation function)

**Step 1: Update sendMessage to use new URL pattern**

Replace lines 294-300:

```javascript
      // Redirect to conversation view if we're on the list view
      const chatOutput = document.getElementById('chatOutput');
      if (!chatOutput) {
        // We're on list view, redirect to conversation with pending message
        window.location.href = `/explorations/${currentConversationId}?message=${encodeURIComponent(message)}`;
        return;
      }

      // Update URL to new conversation (we're in the chat view)
      history.replaceState({}, '', `/explorations/${currentConversationId}`);
```

**Step 2: Update loadConversation URL update**

Replace line 1117:

```javascript
    // Update URL without reload
    window.history.replaceState({}, '', `/explorations/${convId}`);
```

**Step 3: Update startFreshConversation URL**

Replace line 1154:

```javascript
  window.history.replaceState({}, '', '/explorations/new');
```

**Step 4: Update htmx afterSwap handler for new URL pattern**

Replace lines 40-47:

```javascript
    // Check if we're on a conversation page
    const path = window.location.pathname;
    const convMatch = path.match(/^\/explorations\/([a-f0-9-]+)$/);
    if (convMatch && convMatch[1] !== currentConversationId) {
      currentConversationId = convMatch[1];
      loadConversation(convMatch[1]);
    } else if (path === '/explorations' || path === '/explorations/new') {
      currentConversationId = null;
    }
```

**Step 5: Commit**

```bash
git add web/static/js/chat.js && git commit -m "js: update chat for new URL structure and deferred creation"
```

---

## Task 12: Update Sidebar Active State Script

**Files:**
- Modify: `web/templates/base.html:129-141`

**Step 1: Update updateSidebarActive for new URL patterns**

Replace the script:

```html
  <script>
  function updateSidebarActive() {
    const path = window.location.pathname;
    document.querySelectorAll('.sidebar-nav .nav-link, .offcanvas .nav-link').forEach(link => {
      const href = link.getAttribute('href');
      // Exact match or prefix match for /explorations/<id>
      const isActive = path === href ||
        (href === '/explorations/new' && path === '/explorations/new') ||
        (href.startsWith('/explorations/') && path === href);
      link.classList.toggle('active', isActive);
    });
  }
  // Update on page load and htmx navigation
  document.addEventListener('DOMContentLoaded', updateSidebarActive);
  document.body.addEventListener('htmx:pushedIntoHistory', updateSidebarActive);
  </script>
```

**Step 2: Commit**

```bash
git add web/templates/base.html && git commit -m "template: update sidebar active state for new URL patterns"
```

---

## Task 13: Create Migration Script

**Files:**
- Create: `scripts/migrate_conversation_authors.py`

**Step 1: Write the migration script**

```python
#!/usr/bin/env python3
"""
Migrate existing conversations to have user_id set.

Run in each environment with the appropriate DEFAULT_USER:
  LOCAL:  DEFAULT_USER=admin@localhost python scripts/migrate_conversation_authors.py
  REMOTE: DEFAULT_USER=matometa@inclusion.gouv.fr python scripts/migrate_conversation_authors.py
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "data/matometa.db")
DEFAULT_USER = os.getenv("DEFAULT_USER", "admin@localhost")


def migrate():
    """Update all conversations with NULL or empty user_id."""
    db_path = Path(DB_PATH)
    if not db_path.exists():
        print(f"Database not found at {db_path}")
        return

    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()

    # Count before
    cursor.execute("SELECT COUNT(*) FROM conversations WHERE user_id IS NULL OR user_id = ''")
    before_count = cursor.fetchone()[0]

    if before_count == 0:
        print("No conversations need migration.")
        conn.close()
        return

    # Update
    cursor.execute(
        "UPDATE conversations SET user_id = ? WHERE user_id IS NULL OR user_id = ''",
        (DEFAULT_USER,)
    )
    updated = cursor.rowcount

    conn.commit()
    conn.close()

    print(f"Updated {updated} conversations with user_id = {DEFAULT_USER}")


if __name__ == "__main__":
    migrate()
```

**Step 2: Commit**

```bash
git add scripts/migrate_conversation_authors.py && git commit -m "scripts: add migration for conversation authors"
```

---

## Task 14: Run Local Migration

**Step 1: Run migration locally**

```bash
DEFAULT_USER=admin@localhost .venv/bin/python scripts/migrate_conversation_authors.py
```

**Step 2: Verify**

```bash
sqlite3 data/matometa.db "SELECT user_id, COUNT(*) FROM conversations GROUP BY user_id"
```

Expected: All conversations should have `user_id = admin@localhost`

---

## Task 15: Test Locally

**Step 1: Start the dev server**

```bash
.venv/bin/python -m web.app
```

**Step 2: Manual test checklist**

- [ ] Visit `/explorations` - see conversation list
- [ ] Click "Nouvelle conversation" - goes to `/explorations/new`, input focused
- [ ] Type message and send - conversation created, URL updates to `/explorations/<uuid>`
- [ ] Sidebar shows new conversation
- [ ] Click conversation in sidebar - loads correctly
- [ ] Old URL `/explorations?conv=<uuid>` redirects to `/explorations/<uuid>`

**Step 3: Commit any fixes if needed**

---

## Task 16: Run Remote Migration

**Step 1: SSH to remote and run migration**

```bash
ssh matometa@ljt.cc "cd /srv/matometa && DEFAULT_USER=matometa@inclusion.gouv.fr python scripts/migrate_conversation_authors.py"
```

**Step 2: Verify**

```bash
ssh matometa@ljt.cc "sqlite3 /srv/matometa/data/matometa.db 'SELECT user_id, COUNT(*) FROM conversations GROUP BY user_id'"
```

---

## Summary

16 tasks total:
1. Config: DEFAULT_USER
2. Auth: fallback to DEFAULT_USER
3. Database: user filtering
4. API: filter by user
5. HTML routes: sidebar data
6. HTML routes: new URL structure
7. Template: sidebar redesign
8. Template: mobile nav
9. CSS: conversation list styles
10. Template: explorations updates
11. JavaScript: deferred creation + new URLs
12. Template: sidebar active state
13. Script: migration
14. Run local migration
15. Test locally
16. Run remote migration
