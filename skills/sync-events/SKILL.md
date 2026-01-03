# Sync Events Skill

Synchronize Matomo event documentation with actual codebase tracking.

## When to Use

- When updating a site's event documentation
- When verifying that tracked events match what's in the code
- When investigating "dead" events (in code but never fired)
- When finding undocumented events (fired but not in docs)

## Two-Pronged Approach

### 1. Query Matomo (What's Actually Firing)

```python
from scripts.matomo import MatomoAPI
api = MatomoAPI()

# Get event categories with counts
cats = api.get_event_categories(site_id=SITE_ID, period='month', date='last3')

# Get event actions
actions = api.get_event_actions(site_id=SITE_ID, period='month', date='last3')

# Get event names
names = api.get_event_names(site_id=SITE_ID, period='month', date='last3')
```

This shows what's actually being tracked in production.

### 2. Explore Codebase (What's in the Code)

Use a subagent to explore the repository:

```
Search for:
- `_paq.push` - direct Matomo calls
- `trackEvent` - tracking function calls
- `matomo_event` - Django template tags
- `data-matomo-` - HTML data attributes
- Analytics/tracking modules
```

#### Known Patterns by Framework

**Django (les-emplois):**
- Template tag: `{% matomo_event "category" "action" "name" %}`
- JS handler: catches `data-matomo-*` attributes
- Context processor: sets custom dimensions

**React/Vue:**
- Look for analytics hooks or HOCs
- Event handler wrappers

### 4. Finding Hidden Dynamic Events

Matomo often shows categories/names that don't appear as literals in the code.

#### Dynamic Category Names
Look for string concatenation in templates:
```django
{% matomo_event "connexion "|add:matomo_account_type "clic" "..." %}
```
Trace the variable to its source (often an enum):
```python
# itou/users/enums.py
MATOMO_ACCOUNT_TYPE = {
    UserKind.PRESCRIBER: "prescripteur",
    UserKind.EMPLOYER: "employeur inclusif",
}
```

#### Dynamic Event Names
Look for patterns like:
```django
{% matomo_event "category" "clic" "prefix-"|add:variable %}
```
Examples found in les-emplois:
- `"voir-liste-candidatures-"|add:category.name` → appends status (À traiter, En attente)
- `"candidature_"|add:request.user.get_kind_display` → appends user type

#### Python f-strings in Views
Multi-step wizards often build names dynamically:
```python
matomo_event_name = f"batch-refuse-application-{self.step}-submit"
```

#### Search Strategy
1. Query Matomo for actual categories/names
2. Search codebase for literal matches
3. For unmatched events, search for:
   - `|add:` in templates (Django concatenation)
   - `f"...{` in Python (f-strings)
   - `+ ` near matomo/tracking keywords
4. Trace variables back to enums, view context, or model fields

#### Common Sources of Dynamic Values
- User type enums (`UserKind`, `MATOMO_ACCOUNT_TYPE`)
- Status/state fields from models
- Wizard step names
- URL parameters or form values

### 3. Cross-Reference

Compare the two sources:

| Status | Meaning |
|--------|---------|
| ✓ In code + In Matomo | Working, documented |
| ⚠ In code, not in Matomo | Dead code or new/rare event |
| ⚠ In Matomo, not in code | Legacy or external source |

## Output Format

Update the site's knowledge file with:

```markdown
## Matomo Events

Scraped from codebase YYYY-MM-DD. ~N events tracked.

### Implementation
[How events are tracked in this codebase]

### Event Categories

#### category_name (N events)
[Business context for this category]

| Action | Name | Description |
|--------|------|-------------|
| action | name | What triggers this |
```

## Caveats

- **Tagging plans drift**: Developers add tracking but don't document it
- **Dead events**: Code exists but feature unused or removed
- **Dynamic values**: Some event names are computed at runtime
- **Consent**: Events may not fire if user declines tracking

## Repositories

| Site | GitHub |
|------|--------|
| Emplois | https://github.com/gip-inclusion/les-emplois |
| Marché | https://github.com/gip-inclusion/le-marche |
| DORA | https://github.com/gip-inclusion/dora |
| RDV-Insertion | https://github.com/gip-inclusion/rdv-insertion |
