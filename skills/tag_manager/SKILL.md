---
name: tag_manager
description: Manage Matomo Tag Manager triggers, tags, and deployments with POST operations and validation
---

# Matomo Tag Manager Skill

## When to Use This Skill

Use this skill when you need to:
- Create triggers (click tracking, page views, form submissions)
- Create tags (custom HTML, Matomo events, third-party integrations)
- Deploy tags to environments (live, staging, dev)
- Add Tally feedback forms or other popups
- Test changes with preview mode before publishing
- Manage Tag Manager workflow (draft → test → publish → cleanup)

## Prerequisites

Before using Tag Manager operations:

1. **Know your site ID and container ID** - Check `knowledge/sites/` for site details
2. **Read tag-manager.md** - `knowledge/matomo/tag-manager.md` for concepts
3. **Understand draft vs live** - Draft IDs ≠ Published IDs (they change on publish)

## Core Workflow

All Tag Manager operations use `lib.query`:

```python
from lib.query import get_matomo

api = get_matomo("inclusion")
```

### Complete Example: Click Tracking

```python
from lib.query import get_matomo

api = get_matomo("inclusion")

# 1. Get draft version
draft_id = api.get_draft_version(site_id=210, container_id="xg8aydM9")

# 2. Create trigger
trigger_id = api.add_trigger(
    site_id=210,
    container_id="xg8aydM9",
    version_id=draft_id,
    trigger_type="AllElementsClick",
    name="Button clicks",
    conditions=[
        {"comparison": "contains", "actual": "ClickClasses", "expected": "btn-primary"}
    ]
)

# 3. Create tag
tag_id = api.add_tag(
    site_id=210,
    container_id="xg8aydM9",
    version_id=draft_id,
    tag_type="CustomHtml",
    name="Log clicks",
    parameters={
        "customHtml": "<script>console.log('clicked!');</script>",
        "htmlPosition": "bodyEnd"
    },
    fire_trigger_ids=[trigger_id],
    fire_limit="once_page"
)

# 4. Test with preview
api.enable_preview(site_id=210, container_id="xg8aydM9")
# → Visit site in browser, verify behavior

# 5. Publish
api.publish_version(
    site_id=210,
    container_id="xg8aydM9",
    version_id=draft_id,
    environment="live"
)

# 6. Cleanup (optional - delete from BOTH draft and live)
api.disable_preview(site_id=210, container_id="xg8aydM9")
```

---

## Common Pattern: Tally Form Popup

Trigger a Tally feedback form when users view a specific page (bottom-right popup).

```python
from lib.query import get_matomo

api = get_matomo("inclusion")
draft_id = api.get_draft_version(site_id=210, container_id="xg8aydM9")  # Dora staging

# 1. Trigger: PageView on service detail pages
trigger_id = api.add_trigger(
    site_id=210,
    container_id="xg8aydM9",
    version_id=draft_id,
    trigger_type="PageView",
    name="XP BENEF - Vue d'une page Service",
    conditions=[
        {"comparison": "starts_with", "actual": "PageUrl",
         "expected": "https://dora-staging.inclusion.beta.gouv.fr/services/"}
    ]
)

# 2. Tag: Tally embed code (bottom-right popup)
tag_id = api.add_tag(
    site_id=210,
    container_id="xg8aydM9",
    version_id=draft_id,
    tag_type="CustomHtml",
    name="XP - appel tag Tally",
    parameters={
        "customHtml": """<script>
            (function(d,t) {
                var s=d.createElement(t),options={'formId':'YOUR_FORM_ID','popup':{'open':{'trigger':'time','ms':2000},'layout':'default','autoClose':30000}};
                s.src='https://tally.so/widgets/embed.js';
                s.onload=function(){Tally.loadEmbeds(options);};
                d.head.appendChild(s);
            })(document,'script');
        </script>""",
        "htmlPosition": "bodyEnd"
    },
    fire_trigger_ids=[trigger_id],
    fire_limit="once_24hours",  # Don't annoy users every page
    status="active"
)

# 3. Test with preview before publishing
api.enable_preview(site_id=210, container_id="xg8aydM9")
# Visit the service page in your browser to test

# 4. Publish when ready
api.publish_version(
    site_id=210,
    container_id="xg8aydM9",
    version_id=draft_id,
    environment="live"
)
```

**Key parameters explained:**
- `trigger_type="PageView"` — fires when page loads
- `conditions` with `starts_with` — matches all service detail pages
- `fire_limit="once_24hours"` — prevents popup spam
- Tally's `popup` config controls timing and position

---

## Gotchas

### 1. Draft vs Published IDs Change

When you publish, Matomo creates a **new version** and assigns **new IDs** to all objects:

```
draft (v420)              publication              v972 (live)
  trigger 13994    ──────────────────────────→   trigger 14030
  tag     11149    ──────────────────────────→   tag     11170
```

**Keep draft IDs** if you need to update/delete later in the draft.

### 2. Delete from Both Draft and Live

Deleting from draft doesn't remove from published versions. To fully remove:

```python
# Delete from draft
api.delete_trigger(site_id=210, container_id="xg8aydM9", version_id=DRAFT_ID, trigger_id=DRAFT_TRIGGER_ID)

# Also delete from live version
api.delete_trigger(site_id=210, container_id="xg8aydM9", version_id=LIVE_VERSION, trigger_id=LIVE_TRIGGER_ID)

# Then re-publish
api.publish_version(site_id=210, container_id="xg8aydM9", version_id=DRAFT_ID, environment="live")
```

### 3. Preview Mode Uses Cookies

`enable_preview()` sets a cookie in your browser. The site loads the draft version when the cookie is present. Clear cookies or use `disable_preview()` to return to live.

---

## Available Methods

### Container Operations

```python
# Get container info (includes draft and releases)
container = api.get_container(site_id=210, container_id="xg8aydM9")

# Quick access to draft version ID
draft_id = api.get_draft_version(site_id=210, container_id="xg8aydM9")
```

### Trigger Operations

```python
# Add trigger (validates trigger_type)
trigger_id = api.add_trigger(
    site_id, container_id, version_id,
    trigger_type="PageView",  # AllElementsClick, FormSubmit, etc.
    name="My Trigger",
    conditions=[{"comparison": "equals", "actual": "PageUrl", "expected": "/test"}]
)

# Update trigger
api.update_trigger(site_id, container_id, version_id, trigger_id, name="New Name")

# Delete trigger
api.delete_trigger(site_id, container_id, version_id, trigger_id)
```

**Valid trigger types:** `AllElementsClick`, `AllLinksClick`, `PageView`, `FormSubmit`, `HistoryChange`, `WindowLoaded`, `ElementVisibility`, `CustomEvent`

**Condition operators:** `equals`, `contains`, `starts_with`, `ends_with`, `matches_regex`, etc.

### Tag Operations

```python
# Add tag (validates tag_type and fire_limit)
tag_id = api.add_tag(
    site_id, container_id, version_id,
    tag_type="CustomHtml",
    name="My Tag",
    parameters={"customHtml": "<script>...</script>", "htmlPosition": "bodyEnd"},
    fire_trigger_ids=[trigger_id],
    fire_limit="unlimited",  # or once_page, once_24hours, once_lifetime
    status="active",
    priority=999
)

# Update tag
api.update_tag(site_id, container_id, version_id, tag_id, name="New Name")

# Delete tag
api.delete_tag(site_id, container_id, version_id, tag_id)

# Pause tag (temporarily disable)
api.pause_tag(site_id, container_id, version_id, tag_id)

# Resume tag (re-enable)
api.resume_tag(site_id, container_id, version_id, tag_id)
```

**Valid tag types:** `CustomHtml`, `Matomo`, `LinkedinInsight`

**Valid fire limits:** `unlimited`, `once_page`, `once_24hours`, `once_lifetime`

**Valid HTML positions:** `headStart`, `headEnd`, `bodyStart`, `bodyEnd`

### Workflow Operations

```python
# Publish draft to environment (validates environment)
api.publish_version(
    site_id, container_id, version_id,
    environment="live"  # or staging, dev, production, pentest, preview
)

# Enable preview mode (test draft without publishing)
api.enable_preview(site_id, container_id)

# Disable preview mode
api.disable_preview(site_id, container_id)

# Export version for debugging
data = api.export_version(site_id, container_id, version_id)
print(f"Triggers: {len(data['triggers'])}, Tags: {len(data['tags'])}")
```

**Valid environments:** `live`, `staging`, `dev`, `production`, `pentest`, `preview`

---

## Validation

All helper methods validate parameters before making API calls:

- **trigger_type** must be in `VALID_TRIGGER_TYPES`
- **tag_type** must be in `VALID_TAG_TYPES`
- **fire_limit** must be in `VALID_FIRE_LIMITS`
- **environment** must be in `VALID_ENVIRONMENTS`

Invalid values raise `ValueError` with clear error messages listing valid options.

---

## Generic POST for Advanced Use

For Tag Manager operations not covered by helpers, use the generic `post()` method:

```python
# Generic POST with automatic parameter flattening
result = api.post(
    "TagManager.addContainerVariable",
    idSite=210,
    idContainer="xg8aydM9",
    idContainerVersion=420,
    type="DataLayer",
    name="myVariable",
    parameters={"dataLayerName": "customData"}
)
```

Python dicts/lists are automatically flattened to PHP array notation.

---

## Reference

- **Tag Manager concepts:** `knowledge/matomo/tag-manager.md`
- **Site knowledge:** `knowledge/sites/<site-name>.md`
- **Matomo Tag Manager docs:** https://developer.matomo.org/api-reference/reporting-api#TagManager
