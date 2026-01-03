# Cyberputois Journal

> Here are all the updates to the context engine (ie, AGENTS.md, ./knowledge and ./skills).
> New entries are added to the top of the list.

- 2026-01-03. Fixed _UI_MAPPING with correct Matomo category/subcategory IDs discovered via API.getWidgetMetadata. Added exploring-web-ui skill for testing UI links.
- 2026-01-03. Extended querying skill with 5 new modules: Events (get_event_categories/actions/names), Entry/Exit pages, Transitions (page flow), VisitTime (by hour/day), Referrers (types/websites/search/social). Updated _UI_MAPPING and SKILL.md documentation.
- 2026-01-03. Updated AGENTS.md: clarified data sourcing rules — every data point needs a clickable Matomo UI link + raw API call.
- 2026-01-03. Added `get_ui_url()` and `format_data_source()` to scripts/matomo.py: generates clickable Matomo web UI links from API method calls. Maps API methods to UI categories.
- 2026-01-03. Added 2025 traffic baselines to emplois.md: monthly visitor stats, user type distribution by month, baseline proportions (employer:prescriber ~1.3:1 site-wide), custom dimensions reference.
- 2026-01-03. Edited example.md: added baseline levels of widgets.
