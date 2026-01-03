---
name: querying-matomo
description: Query the Matomo analytics API to get visitor stats, page views, custom dimensions, and segmented data. Use this skill whenever you need to retrieve web analytics data.
---

# Querying the Matomo API

## When to use this skill

Use this skill when you need to:
- Get visitor counts, page views, or engagement metrics
- Analyze traffic by user type, department, or organization
- Query specific page URLs or URL patterns
- Compare metrics across time periods

## Prerequisites

Before querying, you MUST:
1. Read the relevant knowledge file from `./knowledge/` for the site you're querying
2. Load credentials from `.env` (MATOMO_URL, MATOMO_API_KEY)
3. Know the site ID (found in knowledge files or via `SitesManager.getSitesWithAtLeastViewAccess`)

## Quick start with Python

Use the helper library in `scripts/matomo.py`:

```python
from scripts.matomo import MatomoAPI

api = MatomoAPI()  # loads credentials from .env

# Get visit summary
summary = api.get_visits(site_id=117, period="month", date="2025-12-01")
print(f"Unique visitors: {summary['nb_uniq_visitors']}")

# Get custom dimension breakdown (e.g., UserKind)
user_types = api.get_dimension(site_id=117, dimension_id=1, period="month", date="2025-12-01")

# Query with URL segment
gps_visits = api.get_visits(site_id=117, period="month", date="2025-12-01", segment="pageUrl=@/gps/")
```

## API reference

### Base URL format

```
https://{MATOMO_URL}/?module=API&method={METHOD}&format=JSON&token_auth={API_KEY}
```

### Core methods

| Method | Purpose |
|--------|---------|
| `VisitsSummary.get` | Full visit metrics (visitors, actions, bounce rate, etc.) |
| `VisitsSummary.getUniqueVisitors` | Just unique visitor count |
| `Actions.getPageUrls` | Page-level stats; use `filter_pattern` to filter URLs |
| `CustomDimensions.getCustomDimension` | Breakdown by custom dimension |
| `CustomDimensions.getConfiguredCustomDimensions` | List available dimensions for a site |

### Parameters

**Required for most methods:**
- `idSite` — site ID (integer)
- `period` — `day`, `week`, `month`, or `year`
- `date` — `today`, `yesterday`, `YYYY-MM-DD`, or `lastN`

**Optional:**
- `segment` — filter visits (see Segments below)
- `filter_limit` — max rows returned (default 100)
- `flat` — set to `1` to flatten hierarchical data

### Segments

Segments filter the data to a subset of visits. Format: `dimension==value` or `dimension=@value` (contains).

Common segments:
```
pageUrl=@/gps/              # visits that viewed any /gps/ page
pageUrl==/exact/path        # visits that viewed exactly this path
dimension1==prescriber      # visits where UserKind is "prescriber"
```

Combine with `;` (AND) or `,` (OR):
```
pageUrl=@/gps/;dimension1==employer
```

URL-encode the segment when using curl:
```
segment=pageUrl%3D%40%2Fgps%2F
```

### Custom dimensions

Each site may have custom dimensions configured. Query them first:

```
method=CustomDimensions.getConfiguredCustomDimensions&idSite=117
```

Returns dimension metadata including:
- `idcustomdimension` — internal ID
- `index` — the dimension index (use this in queries)
- `scope` — `visit` or `action`
- `name` — human-readable name

To query a dimension, use its **index** as `idDimension`:
```
method=CustomDimensions.getCustomDimension&idSite=117&idDimension=1&period=month&date=2025-12-01
```

### Known custom dimensions (Emplois - site 117)

| Index | Scope | Name |
|-------|-------|------|
| 1 | visit | UserKind |
| 1 | action | UserOrganizationKind |
| 2 | action | UserDepartment |

Note: Visit-scoped dimensions use idDimension=1, action-scoped use idDimension=3 or 4 (the idcustomdimension value).

## Handling timeouts

Segment queries on large date ranges can timeout. Strategies:
1. Use `period=week` and query each week separately
2. Add `filter_limit` to reduce response size
3. Use more specific segments

## Data freshness

Matomo archives data with a 1-3 day lag. If "today" returns 0, try `date=last7` to find the most recent available data.

## Output format

Always document your queries in reports with:
- The full API URL (with token redacted)
- Date range queried
- Any segments applied
- Timestamp of when data was retrieved
