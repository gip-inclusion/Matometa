---
name: matomo_query
description: Query the Matomo analytics API to get visitor stats, page views, custom dimensions, and segmented data. Use this skill whenever you need to retrieve web analytics data. (project)
---

# Querying the Matomo API

## When to use this skill

Use this skill when you need to:
- Get visitor counts, page views, or engagement metrics
- Analyze traffic by user type, department, or organization
- Query specific page URLs or URL patterns
- Compare metrics across time periods
- Track events (button clicks, form submissions, feature usage)
- Analyze user journeys (entry pages, exit pages, page flow)
- Understand temporal patterns (by hour, by day of week)
- Identify traffic sources (referrers, search engines, social)

## Prerequisites

Before querying, you MUST:
1. Read the relevant knowledge file from `./knowledge/` for the site you're querying
2. Load credentials from `.env` (MATOMO_URL, MATOMO_API_KEY)
3. Know the site ID (found in knowledge files or via `SitesManager.getSitesWithAtLeastViewAccess`)

## Quick start with Python

Use the helper library in `skills/matomo_query/scripts/matomo.py`:

```python
# From project root (recommended):
from scripts.matomo import MatomoAPI

# Or directly:
from skills.matomo_query.scripts.matomo import MatomoAPI

api = MatomoAPI()  # loads credentials from .env

# Get visit summary
summary = api.get_visits(site_id=117, period="month", date="2025-12-01")
print(f"Unique visitors: {summary['nb_uniq_visitors']}")

# Get custom dimension breakdown (e.g., UserKind)
user_types = api.get_dimension(site_id=117, dimension_id=1, period="month", date="2025-12-01")

# Query with URL segment
gps_visits = api.get_visits(site_id=117, period="month", date="2025-12-01", segment="pageUrl=@/gps/")

# Get events
events = api.get_event_categories(site_id=117, period="month", date="2025-12-01")

# Get entry/exit pages
landing = api.get_entry_pages(site_id=117, period="month", date="2025-12-01")
exits = api.get_exit_pages(site_id=117, period="month", date="2025-12-01")

# Get page flow (what happens before/after a page)
flow = api.get_transitions(site_id=117, period="month", date="2025-12-01", page_url="/gps/groups/list")

# Get temporal patterns
by_hour = api.get_visits_by_hour(site_id=117, period="month", date="2025-12-01")
by_day = api.get_visits_by_day_of_week(site_id=117, period="month", date="2025-12-01")

# Get traffic sources
referrers = api.get_referrers(site_id=117, period="month", date="2025-12-01")
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
| `Actions.getEntryPageUrls` | Landing pages (first page of visits) |
| `Actions.getExitPageUrls` | Exit pages (last page of visits) |
| `CustomDimensions.getCustomDimension` | Breakdown by custom dimension |
| `CustomDimensions.getConfiguredCustomDimensions` | List available dimensions for a site |
| `Events.getCategory` | Event categories with counts |
| `Events.getAction` | Event actions with counts |
| `Events.getName` | Event names with counts |
| `Referrers.getReferrerType` | Traffic sources by type (direct, search, social, etc.) |
| `Referrers.getWebsites` | Referring websites |
| `Referrers.getSearchEngines` | Search engines driving traffic |
| `Referrers.getSocials` | Social networks driving traffic |
| `VisitTime.getVisitInformationPerServerTime` | Visits by hour of day |
| `VisitTime.getByDayOfWeek` | Visits by day of week |
| `Transitions.getTransitionsForAction` | Page flow (before/after a specific page) |

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

Segments filter the data to a subset of visits.

**IMPORTANT: Use saved segments whenever possible.** Each site has pre-defined segments
(listed in `## Saved Segments` in the site's knowledge file) that are optimized and
pre-archived by Matomo. These are much faster than custom segments and avoid timeouts.

Check the site knowledge file first:
- `knowledge/sites/emplois.md` → 39 saved segments
- `knowledge/sites/dora.md` → 29 saved segments
- etc.

Common saved segment patterns across sites:
- `RETENTION - dernière visite 30j` — returning users within 30 days
- `PROFILE - connecté` / `PROFILE - Logged in` — authenticated users
- `DEVICE - mobile` / `DEVICE - Smartphone` — mobile visitors
- `SOURCE - ...` — traffic from specific sources

**Custom segments** (when no saved segment fits) use format `dimension==value` or `dimension=@value` (contains).

Common custom segments:
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

### Events

Events track user interactions beyond page views: button clicks, form submissions, feature usage.

Matomo events have a 3-level hierarchy:
- **Category**: broad grouping (e.g., "GPS", "Candidacy", "Form")
- **Action**: what happened (e.g., "click", "submit", "view")
- **Name**: specific element (e.g., "approve_button", "search_form")

```python
# Get all event categories
categories = api.get_event_categories(site_id=117, period="month", date="2025-12-01")
# Returns: [{"label": "GPS", "nb_events": 1234, "nb_visits": 567}, ...]

# Get event actions
actions = api.get_event_actions(site_id=117, period="month", date="2025-12-01")

# Combine with segments to analyze events for specific user types
events = api.get_event_categories(
    site_id=117, period="month", date="2025-12-01",
    segment="dimension1==prescriber"
)
```

### Entry and exit pages

Understand where users land and where they leave:

```python
# Top landing pages
entry = api.get_entry_pages(site_id=117, period="month", date="2025-12-01")
# Returns: [{"label": "/", "entry_nb_visits": 5000, "entry_bounce_count": 200}, ...]

# Top exit pages
exit = api.get_exit_pages(site_id=117, period="month", date="2025-12-01")
# Returns: [{"label": "/dashboard", "exit_nb_visits": 3000, "exit_rate": "15%"}, ...]
```

### Transitions (page flow)

Analyze what users do before and after visiting a specific page:

```python
flow = api.get_transitions(
    site_id=117,
    period="month",
    date="2025-12-01",
    page_url="/gps/groups/list"
)
# Returns dict with:
# - previousPages: what pages led here
# - followingPages: where users went next
# - referrers: external sources
# - outlinks: external links clicked
```

Use case: "What do users do after viewing the GPS group list?"

**Note:** Transitions queries are expensive. Use `period="week"` instead of `"month"` to avoid timeouts.

### Visit time patterns

Understand when users are active:

```python
# By hour (0-23)
hourly = api.get_visits_by_hour(site_id=117, period="month", date="2025-12-01")
# Returns 24 items, one per hour

# By day of week (1=Monday, 7=Sunday)
daily = api.get_visits_by_day_of_week(site_id=117, period="month", date="2025-12-01")
# Returns 7 items
```

Use case: "Is GPS used during work hours or after?"

### Referrers

Understand traffic sources:

```python
# Overview by type
types = api.get_referrers(site_id=117, period="month", date="2025-12-01")
# Returns: Direct Entry, Search Engines, Websites, Social Networks, Campaigns

# Drill down
websites = api.get_referrer_websites(site_id=117, period="month", date="2025-12-01")
search = api.get_referrer_search_engines(site_id=117, period="month", date="2025-12-01")
social = api.get_referrer_socials(site_id=117, period="month", date="2025-12-01")
```

## Handling timeouts

Segment queries on large date ranges frequently timeout (30s server limit).

**Symptoms:**
- curl returns HTML instead of JSON (`<!DOCTYPE html>`)
- jq fails with "parse error: Invalid numeric literal at line 1, column 10"
- Python client raises `MatomoError`

**Strategies:**

1. **Use saved segments instead of custom ones:**
   Saved segments (listed in each site's knowledge file) are pre-archived by Matomo
   and return instantly. Custom segments must be computed on-the-fly and often timeout.
   ```python
   # Check knowledge/sites/{site}.md for available saved segments
   # Use the segment definition from the "Saved Segments" table
   ```

2. **Query single months, not ranges:**
   ```bash
   # BAD: year-long range with segment
   date=2025-01-01,2025-12-31&segment=pageUrl%3D%40%2Fgps%2F

   # GOOD: single month
   date=2025-12-01&period=month&segment=pageUrl%3D%40%2Fgps%2F
   ```

3. **Use `period=week` for expensive queries:**
   ```python
   # Month query times out? Try weekly:
   data = api.get_dimension_by_week(site_id=117, dimension_id=1, year=2025, month=12, segment="pageUrl=@/gps/")
   ```

4. **Reduce segment complexity:**
   - Start with no segment, add incrementally
   - Avoid combining multiple segment conditions on large date ranges

5. **Add `filter_limit` to reduce response size:**
   ```bash
   &filter_limit=20  # only top 20 results
   ```

6. **Check response type before parsing:**
   ```bash
   response=$(curl -s "...")
   if echo "$response" | grep -q "DOCTYPE"; then
     echo "Timeout error"
   else
     echo "$response" | jq .
   fi
   ```

**Known expensive queries:**
- `CustomDimensions.getCustomDimension` with URL segment on multi-month ranges
- `Events.getName` with segment
- Any query combining `segment=` with `date=YYYY-MM-DD,YYYY-MM-DD` ranges

## Data freshness

Matomo archives data with a 1-3 day lag. If "today" returns 0, try `date=last7` to find the most recent available data.

## Output format

Always document your queries in reports with a **Data source** line. Use `format_data_source()`:

```python
from scripts.matomo import format_data_source

source = format_data_source(
    base_url="matomo.inclusion.beta.gouv.fr",
    method="VisitsSummary.get",
    params={"idSite": 117, "period": "month", "date": "2025-12-01", "segment": "pageUrl=@/gps/"}
)
# Returns: "[View in Matomo](https://...) | `VisitsSummary.get?idSite=117&...`"
```

This generates:
1. A clickable link to the Matomo web UI
2. The raw API call for reproducibility
