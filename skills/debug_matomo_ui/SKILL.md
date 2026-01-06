---
name: debug_matomo_ui
description: Test and discover Matomo web UI URLs. Use this skill to find correct category/subcategory values for UI links. (project)
---

# Exploring Matomo Web UI

## When to use this skill

Use this skill when:
- UI links in reports aren't working correctly
- You need to find the correct category/subcategory for a new API method
- You want to verify that a UI URL leads to the expected page

## Prerequisites

1. Get a fresh session cookie from browser dev tools
2. Store it in `.matomo_cookie` (gitignored):
   ```
   MATOMO_SESSID=xxx; cf_clearance=yyy
   ```

## Usage

```python
from scripts.ui_tester import discover_categories, print_categories

# Discover valid categories for a site (uses API, no cookie needed)
categories = discover_categories(site_id=117)

# Print them nicely
print_categories(site_id=117)
# Output:
# General_Actions:
#   Events_Events (Events)
#   General_Pages (Pages)
#   Actions_SubmenuPagesEntry (Entry pages)
#   ...
```

The `discover_categories()` function uses `API.getWidgetMetadata` to get the real category/subcategory IDs - much more reliable than scraping HTML.

## Cookie expiry

The cookie will expire (403 errors). When this happens:
1. Get a fresh cookie from browser
2. Update `.matomo_cookie`
3. Clear the file when done testing

## Known good mappings

After testing, update `_UI_MAPPING` in `skills/querying/scripts/matomo.py`.
