# Building Interactive Apps

Guidelines for creating frontend applications in `/data/interactive/`.

## Stack

- **Vanilla JS** — No React, Vue, or frameworks. Plain JavaScript.
- **Semantic HTML** — Use proper elements (`<nav>`, `<main>`, `<article>`, `<table>`, etc.)
- **CSS** — Custom properties, minimal dependencies. No Tailwind.
- **Charts** — D3.js or Observable Plot for complex visualizations, Chart.js for simpler ones.

## File Structure

Each app lives in its own folder:

```
data/interactive/
└── my-app/
    ├── APP.md              # REQUIRED: metadata (see below)
    ├── index.html          # Entry point
    ├── style.css           # Styles
    ├── app.js              # Application logic
    └── data.json           # Static data (if needed)
```

## APP.md (Required)

Every app **must** have an `APP.md` file with YAML front-matter. This is how the app is discovered and displayed in the Rapports section.

```markdown
---
title: My App Title
description: Short description shown in the card
updated: 2026-01-16
website: emplois
category: Traffic analysis
tags: dashboard, visits, monthly
authors: jean@example.com, marie@example.com
conversation_id: abc-123-def
---

## About

Optional documentation about the app, how to use it, how to regenerate data, etc.
```

**Required fields:**
- `title` — Display name in the reports list

**Optional fields:**
- `description` — Shown below the title in the card
- `updated` — Date in YYYY-MM-DD format (shown in card footer)
- `website` — Associated website (use valid product tags, see below)
- `category` — Category for filtering
- `tags` — Comma-separated or `[tag1, tag2]` format (use valid tags, see below)
- `authors` — Comma-separated email addresses
- `conversation_id` — Links to the conversation that created this app

## Valid Tags

Use these controlled tag values for `website` and `tags` fields:

### Products (for `website` field)
- `emplois` — Emplois
- `dora` — Dora
- `marche` — Marché
- `communaute` — Communauté
- `pilotage` — Pilotage
- `plateforme` — Plateforme
- `rdv-insertion` — RDV-Insertion
- `mon-recap` — Mon Récap
- `multi` — Multi-produits

### Themes (for `tags` field)
**Acteurs:**
- `candidats`, `prescripteurs`, `employeurs`, `structures`, `acheteurs`, `fournisseurs`

**Concepts métier:**
- `iae`, `orientation`, `depot-de-besoin`, `demande-de-devis`, `commandes`

**Métriques:**
- `trafic`, `conversions`, `retention`, `geographique`

### Types de demande (for `tags` field)
- `extraction` — Data extraction
- `analyse` — Analysis/report
- `appli` — Interactive app
- `meta` — Meta/tooling

### Sources (for `tags` field)
- `matomo`, `stats`, `datalake`

Apps without a valid `APP.md` will not appear in the reports list.

## Last Updated Footer

Always include a **last updated date** at the bottom of the page:
```html
<footer>
    <p>Dernière mise à jour : 2026-01-16</p>
</footer>
```

## Styling

### Marianne Font

```css
@font-face {
    font-display: swap;
    font-family: Marianne;
    font-style: normal;
    font-weight: 300;
    src: url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Light.woff2) format("woff2"),
         url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Light.woff) format("woff")
}
@font-face {
    font-display: swap;
    font-family: Marianne;
    font-style: italic;
    font-weight: 300;
    src: url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Light_Italic.woff2) format("woff2"),
         url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Light_Italic.woff) format("woff")
}
@font-face {
    font-display: swap;
    font-family: Marianne;
    font-style: normal;
    font-weight: 400;
    src: url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Regular.woff2) format("woff2"),
         url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Regular.woff) format("woff")
}
@font-face {
    font-display: swap;
    font-family: Marianne;
    font-style: italic;
    font-weight: 400;
    src: url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Regular_Italic.woff2) format("woff2"),
         url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Regular_Italic.woff) format("woff")
}
@font-face {
    font-display: swap;
    font-family: Marianne;
    font-style: normal;
    font-weight: 500;
    src: url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Medium.woff2) format("woff2"),
         url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Medium.woff) format("woff")
}
@font-face {
    font-display: swap;
    font-family: Marianne;
    font-style: normal;
    font-weight: 700;
    src: url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Bold.woff2) format("woff2"),
         url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Bold.woff) format("woff")
}
@font-face {
    font-display: swap;
    font-family: Marianne;
    font-style: italic;
    font-weight: 700;
    src: url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Bold_Italic.woff2) format("woff2"),
         url(https://inclusion.gouv.fr/static/dsfr/dist/fonts/Marianne-Bold_Italic.woff) format("woff")
}

body {
    font-family: Marianne, system-ui, sans-serif;
}
```

### Color Palette

```css
:root {
    /* Primary accents */
    --navy: #000638;
    --periwinkle: #ADB6FF;
    --orange: #E57200;
    --orange-light: #FFA347;

    /* Extended palette */
    --amber: #FFA800;
    --coral: #FF7B91;
    --slate: #4A5F74;
    --teal: #4498A6;
    --cyan: #47D5EC;
    --red: #FF395A;

    /* Semantic */
    --text: var(--navy);
    --text-muted: var(--slate);
    --accent: var(--orange);
    --accent-hover: var(--orange-light);
    --link: var(--teal);
}
```

### Base Styles

```css
* {
    box-sizing: border-box;
}

body {
    font-family: Marianne, system-ui, sans-serif;
    color: var(--text);
    line-height: 1.5;
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
}

h1, h2, h3 {
    color: var(--navy);
}

a {
    color: var(--link);
}

button, .btn {
    background: var(--accent);
    color: white;
    border: none;
    padding: 0.5rem 1rem;
    border-radius: 4px;
    cursor: pointer;
    font-family: inherit;
}

button:hover, .btn:hover {
    background: var(--accent-hover);
}

table {
    width: 100%;
    border-collapse: collapse;
}

th, td {
    padding: 0.5rem;
    text-align: left;
    border-bottom: 1px solid var(--periwinkle);
}

th {
    background: var(--navy);
    color: white;
}
```

## Data Access

### Query API Endpoint

Apps fetch data via `POST /api/query`. The user must be authenticated (oauth2-proxy handles this).

```javascript
async function query(params) {
    const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params)
    });
    return response.json();
}
```

#### Matomo Queries

```javascript
const result = await query({
    source: 'matomo',
    instance: 'inclusion',
    method: 'VisitsSummary.get',
    conversation_id: 'my-app-session-123',  // optional, for audit
    params: {
        idSite: 117,
        period: 'month',
        date: '2025-12-01'
    }
});

if (result.success) {
    console.log(result.data);  // { nb_visits: 405574, ... }
} else {
    console.error(result.error);
}
```

#### Metabase Queries

```javascript
// SQL query
const result = await query({
    source: 'metabase',
    instance: 'stats',       // or 'datalake'
    database_id: 2,
    sql: 'SELECT * FROM candidats LIMIT 10'
});

// Execute saved card
const result = await query({
    source: 'metabase',
    instance: 'stats',
    card_id: 123
});

// Response format
{
    success: true,
    data: {
        columns: ['id', 'name', ...],
        rows: [[1, 'Alice'], [2, 'Bob']],
        row_count: 2
    },
    execution_time_ms: 234
}
```

### Available Instances

| Source | Instance | Description |
|--------|----------|-------------|
| matomo | inclusion | Matomo analytics for all sites |
| metabase | stats | IAE employment statistics (database 2) |
| metabase | datalake | Cross-product analytics (databases 2, 3) |

## Performance Guidelines

### Avoid N+1 Queries

**Bad:**
```javascript
// DON'T: One request per site
for (const siteId of siteIds) {
    const data = await query({
        source: 'matomo',
        instance: 'inclusion',
        method: 'VisitsSummary.get',
        params: { idSite: siteId, period: 'month', date: '2025-12' }
    });
}
```

**Good:**
```javascript
// DO: Batch with idSite=all or date ranges
const data = await query({
    source: 'matomo',
    instance: 'inclusion',
    method: 'VisitsSummary.get',
    params: { idSite: 'all', period: 'month', date: '2025-12' }
});
```

### Use Static Data for Heavy Loads

If initial data load is expensive (>5s or >1MB), pre-generate a static JSON file:

```javascript
// Check for static data first
async function loadData() {
    try {
        const response = await fetch('data.json');
        if (response.ok) {
            return response.json();
        }
    } catch (e) {
        // Fall through to API
    }

    // Fallback to live query
    return query({ ... });
}
```

If the app has a `cron.py`, the data will be refreshed automatically
(see [Scheduled Data Refresh](#scheduled-data-refresh-cron)).
Otherwise, include regeneration instructions in the UI:

```html
<p class="data-note">
    Données statiques du 2026-01-15.
    <a href="#" onclick="showRegenInstructions()">Régénérer</a>
</p>
```

### Caching and Debouncing

```javascript
// Simple cache
const cache = new Map();

async function cachedQuery(params) {
    const key = JSON.stringify(params);
    if (cache.has(key)) {
        return cache.get(key);
    }
    const result = await query(params);
    cache.set(key, result);
    return result;
}

// Debounce for search inputs
function debounce(fn, delay = 300) {
    let timeout;
    return (...args) => {
        clearTimeout(timeout);
        timeout = setTimeout(() => fn(...args), delay);
    };
}

searchInput.addEventListener('input', debounce(async (e) => {
    const results = await cachedQuery({ ... });
    render(results);
}));
```

## Charts

### Chart.js (Simple)

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<canvas id="chart"></canvas>

<script>
new Chart(document.getElementById('chart'), {
    type: 'bar',
    data: {
        labels: ['Jan', 'Feb', 'Mar'],
        datasets: [{
            label: 'Visits',
            data: [120, 150, 180],
            backgroundColor: '#E57200'
        }]
    },
    options: {
        plugins: {
            legend: { display: false }
        }
    }
});
</script>
```

### D3.js / Observable Plot (Complex)

```html
<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
<script src="https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6"></script>

<div id="chart"></div>

<script>
const data = [
    { month: 'Jan', visits: 120 },
    { month: 'Feb', visits: 150 },
    { month: 'Mar', visits: 180 }
];

const chart = Plot.plot({
    marks: [
        Plot.barY(data, { x: 'month', y: 'visits', fill: '#E57200' })
    ],
    style: { fontFamily: 'Marianne' }
});

document.getElementById('chart').append(chart);
</script>
```

## Error Handling

```javascript
async function safeQuery(params) {
    try {
        const result = await query(params);
        if (!result.success) {
            showError(`Erreur: ${result.error}`);
            return null;
        }
        return result.data;
    } catch (e) {
        showError('Impossible de contacter le serveur');
        return null;
    }
}

function showError(message) {
    const el = document.getElementById('error');
    el.textContent = message;
    el.hidden = false;
}
```

## Accessibility

- Use semantic HTML (`<button>` not `<div onclick>`)
- Include `aria-label` for icon-only buttons
- Ensure color contrast meets WCAG AA (4.5:1 for text)
- Support keyboard navigation
- Provide loading states and error messages

## Template

Minimal starter:

```html
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Mon App</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <header>
        <h1>Mon App</h1>
    </header>

    <main>
        <div id="error" hidden class="error"></div>
        <div id="loading" hidden>Chargement...</div>
        <div id="content"></div>
    </main>

    <footer>
        <p>Dernière mise à jour : 2026-01-16</p>
    </footer>

    <script src="app.js"></script>
</body>
</html>
```

## Scheduled Data Refresh (Cron)

Apps can include a `cron.py` script to pre-fetch data on a daily schedule,
avoiding live Matomo API calls on every page load.

### Setup

Add a `cron.py` to your app folder:

```
data/interactive/my-app/
├── APP.md
├── index.html
├── cron.py      ← data refresh script
└── data.json    ← written by cron.py
```

The script runs as a regular Python process with `PYTHONPATH` set to the
project root. It can import `lib.query` to call Matomo/Metabase APIs.
Its working directory is the app folder, so `open('data.json', 'w')` writes
to the right place.

### data.json convention

The `cron.py` script **must** include a `metadata.generated_at` field
(ISO date `YYYY-MM-DD`) in `data.json` so the frontend can show when the
data was last refreshed:

```json
{
  "metadata": {
    "generated_at": "2026-02-12",
    "source": "Matomo API - VisitsSummary.get"
  },
  "2025": { ... }
}
```

The frontend should read this field and display it, for example in the
page footer or near the data:

```javascript
const data = await fetch('data.json').then(r => r.json());
const generatedAt = data.metadata?.generated_at;
if (generatedAt) {
    document.querySelector('footer').textContent =
        `Données mises à jour le ${generatedAt}`;
}
```

```html
<footer>
    <p>Données mises à jour le <span id="generated-at">…</span></p>
</footer>
```

This gives users immediate visibility on data freshness without having
to check the `/cron` page.

### APP.md field

Optionally add `cron: true` or `cron: false` to APP.md front-matter.
Default is `true` when `cron.py` exists. This can be toggled from the UI.

```yaml
---
title: My App
cron: true
---
```

### Running

```bash
python -m web.cron              # run all enabled cron tasks
python -m web.cron --app slug   # run one specific app
python -m web.cron --list       # list discovered cron tasks
python -m web.cron --dry-run    # show what would run
```

On the current VM, set up a system crontab entry:
```
0 6 * * * cd /path/to/autometa && .venv/bin/python -m web.cron
```

### Constraints

- 5-minute timeout per script
- stdout/stderr captured and stored in the database (max 50KB)
- Exit code 0 = success, non-zero = failure
- `.py` files are **not served** via `/interactive/` (404)

### UI

Visit `/cron` to see all cron-eligible apps, their last run status,
and to manually trigger runs or toggle enable/disable.

## Deployment

Apps are served at `/interactive/{folder-name}/`. No build step required.

```
/interactive/my-app/
```

The FastAPI app serves files directly from `data/interactive/`.

**Always use relative URLs** (starting with `/`) when linking to apps or files.
The `BASE_URL` environment variable (e.g., `BASE_URL=https://matometa.ljt.cc/`)
provides the absolute base URL when needed (e.g., for sharing links outside the
app), but relative URLs are the default.

## Data Persistence (Datalake)

Interactive apps are static frontends — they cannot modify the FastAPI backend.
When an app needs to **read and write persistent data** (tracking, assignments,
user notes, state), use the **datalake PostgreSQL** via the existing `/api/query`
endpoint and `lib.query`.

### Why Not FastAPI Routes?

The `web/` directory is baked into the Docker image and NOT bind-mounted.
Any files created or modified under `/app/web/` are written to the container's
overlay filesystem and **vanish on the next restart or deploy**. Never create
FastAPI routes, routers, or Python modules from within the container.

### Architecture

```
Frontend (JS)  ──POST /api/query──▶  FastAPI /api/query  ──▶  Metabase API  ──▶  Datalake PostgreSQL
                                      (already exists)       (native query)     (read + write)
```

The existing `/api/query` endpoint supports full SQL through the Metabase native
query API. The datalake database user has write access, so INSERT, UPDATE, DELETE,
and CREATE TABLE all work.

### The `matometa` Schema

All Autometa tables live in a dedicated `matometa` schema on the datalake,
keeping them separate from the main datalake tables in `public`.

The schema already exists. If you need to verify:

```python
execute_metabase_query(
    instance="datalake", caller=CallerType.AGENT,
    sql="SELECT schema_name FROM information_schema.schemata WHERE schema_name = 'matometa'",
    database_id=2,
)
```

### Setup Pattern

**1. Create your table** (agent-side, Python script):

```python
from lib.query import execute_metabase_query, CallerType

# DDL runs successfully but Metabase reports a parse error (no ResultSet).
# This is normal — ignore the error, the table IS created.
execute_metabase_query(
    instance="datalake",
    caller=CallerType.AGENT,
    sql="""
        CREATE TABLE IF NOT EXISTS matometa.myapp_tracking (
            id SERIAL PRIMARY KEY,
            item_id TEXT NOT NULL,
            assigned_to TEXT,
            status TEXT DEFAULT 'pending',
            note TEXT,
            updated_by TEXT,
            updated_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(item_id)
        )
    """,
    database_id=2,
)
```

**2. Read from the frontend** via `/api/query`:

```javascript
async function loadTracking() {
    const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            source: 'metabase',
            instance: 'datalake',
            database_id: 2,
            sql: 'SELECT * FROM matometa.myapp_tracking ORDER BY updated_at DESC'
        })
    });
    const result = await response.json();
    if (result.success) {
        // result.data = { columns: [...], rows: [...], row_count: N }
        return result.data;
    }
    throw new Error(result.error);
}
```

**3. Write from the frontend** via the same endpoint:

```javascript
async function saveTracking(itemId, assignedTo, status, note, userName) {
    const response = await fetch('/api/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            source: 'metabase',
            instance: 'datalake',
            database_id: 2,
            sql: `INSERT INTO matometa.myapp_tracking (item_id, assigned_to, status, note, updated_by)
                  VALUES ('${itemId}', '${assignedTo}', '${status}', '${note}', '${userName}')
                  ON CONFLICT (item_id) DO UPDATE
                  SET assigned_to = EXCLUDED.assigned_to,
                      status = EXCLUDED.status,
                      note = EXCLUDED.note,
                      updated_by = EXCLUDED.updated_by,
                      updated_at = NOW()
                  RETURNING *`
        })
    });
    return response.json();
}
```

### Important Rules

**Metabase ResultSet quirk:** DDL statements (CREATE TABLE, DROP TABLE, ALTER)
and DML without RETURNING (plain INSERT, UPDATE, DELETE) execute successfully
but Metabase returns an error because it expects a result set. The operation
still completes. **Always use RETURNING** on INSERT/UPDATE/DELETE to get a
proper response, or ignore the error for DDL.

**Schema:** Always use the `matometa` schema (e.g., `matometa.myapp_tracking`,
`matometa.deploy_calendar`). Never create tables in `public`.

**SQL injection:** The example above uses string interpolation for clarity.
In production, sanitize user inputs before embedding them in SQL strings.
The `/api/query` endpoint does not support parameterized queries — validate
and escape values in JavaScript before building the SQL string.

**No schema changes from the frontend.** Only the agent (Python) should run
CREATE TABLE / ALTER TABLE. The frontend should only do SELECT, INSERT, UPDATE,
DELETE on existing tables.
