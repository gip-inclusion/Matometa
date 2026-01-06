# Matomo API Reference

> **Note:** You don't need to read all files here. Load only what's relevant to your query.
> - For most analytics queries: this file + `core-modules.md` is enough
> - For premium features: load the specific module file (cohorts.md, funnels.md, etc.)

Scraped from the Matomo instance on 2026-01-03. This instance includes premium plugins.

## Quick Reference

**50 modules, 450 methods total.**

### Most Used (Core)

| Module | Methods | Description |
|--------|---------|-------------|
| VisitsSummary | 7 | Visits, unique visitors, actions |
| Actions | 18 | Pages, downloads, outlinks, site search |
| CustomDimensions | 7 | UserKind, UserDepartment, etc. |
| Events | 9 | Event tracking |
| Referrers | 17 | Traffic sources |
| VisitFrequency | 1 | Returning vs new visitors |
| Live | 4 | Real-time visitor data |
| Goals | 11 | Goal tracking and ecommerce |
| Transitions | 5 | Page flow analysis |

→ See `core-modules.md` for full signatures.

### Premium Plugins

| Module | Methods | File | Description |
|--------|---------|------|-------------|
| Cohorts | 3 | `cohorts.md` | Cohort analysis by first visit |
| Funnels | 11 | `funnels.md` | Conversion funnel analysis |
| FormAnalytics | 21 | `forms.md` | Form field tracking |
| HeatmapSessionRecording | 24 | `heatmaps.md` | Click maps & session replay |
| AbTesting | 18 | `abtesting.md` | A/B experiments |
| MediaAnalytics | 13 | `media.md` | Video/audio tracking |

### Other Modules

| Module | Methods | Description |
|--------|---------|-------------|
| API | 18 | Metadata, segments, utilities |
| DevicesDetection | 8 | Device/browser/OS |
| UserCountry | 5 | Geolocation |
| VisitorInterest | 6 | Engagement metrics |
| VisitTime | 3 | Time-based analytics |
| SitesManager | 42 | Site configuration |
| TagManager | 38 | Tag management |
| UsersManager | 28 | User management |

→ See `other-modules.md` for full signatures.

## Common Parameters

All analytics methods accept:
- `idSite` - Site ID (117 for Emplois)
- `period` - day, week, month, year, or range
- `date` - YYYY-MM-DD, today, yesterday, lastN
- `segment` - Filter expression (e.g., `pageUrl=@/gps/`)

Optional modifiers:
- `flat=1` - Flatten hierarchical results
- `expanded=1` - Include subtables inline
- `filter_limit=N` - Max rows to return

## Python Client Quick Reference

```python
from skills.matomo_query.scripts.matomo import MatomoAPI
api = MatomoAPI()  # loads credentials from .env

# Core methods
api.get_visits(site_id, period, date, segment=None)           # VisitsSummary.get
api.get_dimension(site_id, dimension_id, period, date, segment=None)  # CustomDimensions
api.get_pages(site_id, period, date, pattern=None, segment=None)      # Actions.getPageUrls
api.get_event_categories(site_id, period, date, segment=None)         # Events.getCategory
api.get_event_actions(site_id, period, date, segment=None)            # Events.getAction
api.get_event_names(site_id, period, date, segment=None)              # Events.getName
api.get_referrers(site_id, period, date, segment=None)                # Referrers.getReferrerType
api.get_transitions(site_id, period, date, page_url, segment=None)    # Transitions

# Run scripts with: PYTHONPATH=. .venv/bin/python scripts/my_script.py
```
