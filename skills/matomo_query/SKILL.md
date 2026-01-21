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

## Prerequisites

Before querying, you MUST:
1. Read the relevant knowledge file from `./knowledge/sites/` for the site you're querying
2. Know the site ID (found in knowledge files)

## Usage

All queries are automatically logged. Use `lib.query`:

```python
from lib.query import execute_matomo_query, CallerType

# Get visit summary
result = execute_matomo_query(
    instance='inclusion',
    caller=CallerType.AGENT,
    method='VisitsSummary.get',
    params={'idSite': 117, 'period': 'month', 'date': '2025-12-01'},
)

if result.success:
    print(result.data)  # {'nb_uniq_visitors': 1234, 'nb_visits': 5678, ...}
else:
    print(f"Error: {result.error}")
```

### Common query patterns

```python
from lib.query import execute_matomo_query, CallerType

# Get visit summary
result = execute_matomo_query(
    instance='inclusion',
    caller=CallerType.AGENT,
    method='VisitsSummary.get',
    params={'idSite': 117, 'period': 'month', 'date': '2025-12-01'},
)

# Get custom dimension breakdown (e.g., UserKind)
result = execute_matomo_query(
    instance='inclusion',
    caller=CallerType.AGENT,
    method='CustomDimensions.getCustomDimension',
    params={'idSite': 117, 'idDimension': 1, 'period': 'month', 'date': '2025-12-01'},
)

# Query with URL segment
result = execute_matomo_query(
    instance='inclusion',
    caller=CallerType.AGENT,
    method='VisitsSummary.get',
    params={'idSite': 117, 'period': 'month', 'date': '2025-12-01', 'segment': 'pageUrl=@/gps/'},
)

# Get events
result = execute_matomo_query(
    instance='inclusion',
    caller=CallerType.AGENT,
    method='Events.getCategory',
    params={'idSite': 117, 'period': 'month', 'date': '2025-12-01'},
)

# Get entry/exit pages
result = execute_matomo_query(
    instance='inclusion',
    caller=CallerType.AGENT,
    method='Actions.getEntryPageUrls',
    params={'idSite': 117, 'period': 'month', 'date': '2025-12-01'},
)

# Get page flow (transitions)
result = execute_matomo_query(
    instance='inclusion',
    caller=CallerType.AGENT,
    method='Transitions.getTransitionsForPageUrl',
    params={'idSite': 117, 'period': 'month', 'date': '2025-12-01', 'pageUrl': '/gps/groups/list'},
)

# Get traffic sources
result = execute_matomo_query(
    instance='inclusion',
    caller=CallerType.AGENT,
    method='Referrers.getAll',
    params={'idSite': 117, 'period': 'month', 'date': '2025-12-01'},
)
```

### Advanced: Direct API access

For convenience methods, use `get_matomo()`:

```python
from lib.query import get_matomo

api = get_matomo(instance='inclusion')

# Convenience methods
summary = api.get_visits(site_id=117, period="month", date="2025-12-01")
dimensions = api.get_dimension(site_id=117, dimension_id=1, period="month", date="2025-12-01")
events = api.get_event_categories(site_id=117, period="month", date="2025-12-01")

# Raw API call for any method
data = api.request("Events.getName", idSite=211, period="month", date="2025-12-01")
```

## CRITICAL: Timeout Prevention

**Matomo has a 30-second query limit. Segmented queries on large date ranges WILL timeout.**

Before running multiple queries:
1. **TEST expensive queries first** - Run ONE query with your segment before looping
2. **Use `period=week` or `period=day`** - Never use month ranges with custom segments
3. **Use saved segments** - Check the site's knowledge file for pre-archived segments (instant)
4. **Combined segments are expensive** - `pageUrl=@X;pageUrl=@Y` queries often timeout

If a query times out, immediately switch to smaller date ranges.

## Available Methods

**Visit metrics:**
- `get_visits(site_id, period, date, segment=None)` - Full visit summary
- `get_unique_visitors(...)` - Just unique visitor count
- `get_visit_frequency(...)` - Returning vs new visitors

**Pages:**
- `get_pages(site_id, period, date, pattern=None, segment=None)` - Page URL stats
- `get_entry_pages(...)` - Landing pages
- `get_exit_pages(...)` - Exit pages
- `get_transitions(site_id, period, date, page_url)` - Page flow analysis

**Custom dimensions:**
- `get_configured_dimensions(site_id)` - List available dimensions
- `get_dimension(site_id, dimension_id, period, date, segment=None)` - Breakdown by dimension

**Events:**
- `get_event_categories(...)` - Event categories with counts
- `get_event_actions(...)` - Event actions with counts
- `get_event_names(...)` - Event names with counts

**Temporal:**
- `get_visits_by_hour(...)` - Distribution by hour
- `get_visits_by_day_of_week(...)` - Distribution by day

**Referrers:**
- `get_referrers(...)` - All referrer types
- `get_referrer_websites(...)` - Referring websites
- `get_referrer_search_engines(...)` - Search engines
- `get_referrer_socials(...)` - Social networks

**Raw API:**
- `request(method, **params)` - Any Matomo API method

## Segments

Segments filter the data to a subset of visits.

**IMPORTANT: Use saved segments whenever possible.** Each site has pre-defined segments
(listed in `## Saved Segments` in the site's knowledge file) that are optimized and
pre-archived by Matomo. These are much faster than custom segments.

**Custom segments** (when no saved segment fits) use format `dimension==value` or `dimension=@value` (contains):
```
pageUrl=@/gps/              # visits that viewed any /gps/ page
pageUrl==/exact/path        # visits that viewed exactly this path
dimension1==prescriber      # visits where UserKind is "prescriber"
```

Combine with `;` (AND) or `,` (OR):
```
pageUrl=@/gps/;dimension1==employer
```

## Data Source Attribution

Include source URLs in reports using `format_data_source()`:

```python
from skills.matomo_query.scripts.ui_mapping import format_data_source

source = format_data_source(
    base_url="matomo.inclusion.beta.gouv.fr",
    method="VisitsSummary.get",
    params={"idSite": 117, "period": "month", "date": "2025-12-01"},
)
# Returns: "[View in Matomo](https://...) | `VisitsSummary.get?idSite=117&...`"
```
