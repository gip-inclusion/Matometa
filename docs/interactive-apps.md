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

Include regeneration instructions in the UI:
```html
<p class="data-note">
    Données statiques du 2026-01-15.
    <a href="#" onclick="showRegenInstructions()">Régénérer</a>
</p>
```

And document the regeneration command:
```markdown
## Regenerating data

Ask Claude: "Regenerate data.json for the my-app interactive app"
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

## Deployment

Apps are served at `/interactive/{folder-name}/`. No build step required.

```
https://matometa.ljt.cc/interactive/my-app/
```

The Flask app serves files directly from `data/interactive/`.
