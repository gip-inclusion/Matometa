---
name: sync_sites
description: Sync site knowledge files with fresh Matomo baselines and events data (project)
---

# Site Sync Skill

Update the knowledge base documents (`knowledge/sites/*.md`) with fresh data from Matomo and codebases.

## Philosophy

This skill **enriches existing documents with objective, measurable data**. It does NOT:
- Generate analyses or interpretations
- Make hypotheses about user behavior
- Add commentary that could bias the agent's reasoning

The goal is to provide **raw facts** that the agent can use as context when answering questions. All data must be:
- **Measurable**: numbers from APIs, not estimates
- **Verifiable**: includes source links or API calls
- **Dated**: always shows when data was retrieved

This keeps the knowledge base clean and prevents the agent from being influenced by stale interpretations.

## Document Structure

Each site document should have a clear separation between:

### Auto-generated sections (managed by this skill)
- `## Traffic Baselines (YYYY)` - Monthly stats tables ONLY
- `## Custom Dimensions` - Dimension list from API
- `## Saved Segments` - Segment list from API
- `## Event Categories` - Category counts from API

### Manual sections (preserved, never overwritten)
- `## Description` - Site context and purpose
- `## Matomo Events` - Detailed event documentation with examples
- `## Feature-Specific Insights` - Analyses tied to specific features
- Any section with >10 lines of content

**IMPORTANT**: Put analyses and insights in SEPARATE sections, not inside Traffic Baselines.
The baselines section will be fully replaced on each sync.

## Usage

```bash
# Full sync (all sites, baselines + events)
python -m skills.sync_sites.scripts.sync_sites

# Baselines only (faster)
python -m skills.sync_sites.scripts.sync_sites --baselines-only

# Single site
python -m skills.sync_sites.scripts.sync_sites --site emplois

# Dry run (show what would be updated)
python -m skills.sync_sites.scripts.sync_sites --dry-run
```

## What it syncs

### Baselines (weekly)

For each site, fetches from Matomo:
- Monthly visitor stats (unique visitors, visits, daily averages)
- User type distribution (if custom dimensions exist)
- Engagement metrics (bounce rate, actions/visit, time on site)

### Custom Dimensions

Fetches configured custom dimensions:
- ID, name, scope (visit or action)
- Active/inactive status

### Saved Segments

Fetches saved segments from Matomo:
- Segment name and definition
- Useful for understanding pre-defined filters

### Event Names

Fetches all event names directly from Matomo:
- Event name, event count, visit count
- Top 50 events shown, sorted by volume
- Data from the reference month (default: last month)

### Event Discovery (manual)

When documenting events, search for these patterns in codebases:

**Django templates:**
- `{% matomo_event "category" "action" "name" %}`
- `data-matomo-category=`, `data-matomo-action=`, `data-matomo-option=`

**Django Python code:**
- `matomo_event_name=`, `matomo_event_option=`
- `matomo_category=`, `matomo_action=`

**JavaScript:**
- `_paq.push(['trackEvent', ...])`
- `Matomo.trackEvent(...)`

## Sites

| Site | Matomo ID | Doc |
|------|-----------|-----|
| emplois | 117 | knowledge/sites/emplois.md |
| pilotage | 146 | knowledge/sites/pilotage.md |
| communaute | 206 | knowledge/sites/communaute.md |
| dora | 211 | knowledge/sites/dora.md |
| plateforme | 212 | knowledge/sites/plateforme.md |
| rdv-insertion | 214 | knowledge/sites/rdv-insertion.md |
| mon-recap | 217 | knowledge/sites/mon-recap.md |
| marche | 136 | knowledge/sites/marche.md |

## Weekly Schedule

Run every Monday morning:
```bash
# Cron entry
0 8 * * 1 cd /path/to/Autometa && python -m skills.sync_sites.scripts.sync_sites
```

Or via launchd on macOS.

## Output

Updates markdown files in place, preserving:
- Header section (URL, GitHub, description)
- Custom sections you've added manually

Regenerates:
- Traffic Baselines tables
- Last sync date
