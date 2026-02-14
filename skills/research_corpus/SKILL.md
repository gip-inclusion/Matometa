---
name: research_corpus
description: Search the qualitative research corpus (interviews, observations, verbatims) to cite field evidence in responses.
---

# Research Corpus — Field Evidence

## What this is

A corpus of qualitative research from the "Connaissance du terrain" Notion workspace.
It contains **interviews with field workers**, **verbatim quotes from users**,
**observations**, **hypotheses**, and **conclusions** about the IAE ecosystem.

This complements your quantitative data (Matomo, Metabase) with human, grounded evidence.

## When to use this

Use this when your answer would benefit from qualitative grounding:

- **"Why" questions** — Analytics shows a drop-off, but why? Field research may explain.
- **Domain topics** — Accompaniment, mobility, digital literacy, prescriber workflows,
  employer needs — the corpus has firsthand accounts.
- **Reports** — Enrich quantitative findings with field quotes and observations.
- **User-facing recommendations** — Back them up with what real people said.

You do NOT need this for purely quantitative questions (traffic counts, conversion rates).

## Usage

```bash
# Basic search
python scripts/search_research.py "mobilité zones rurales"

# Fewer results (default: 5)
python scripts/search_research.py "accompagnement" --limit 3

# Filter by database
python scripts/search_research.py "freins numériques" --db entretiens

# Filter by type
python scripts/search_research.py "difficultés orientation" --type "❝ Verbatim"

# JSON output (for programmatic use)
python scripts/search_research.py "prescripteurs" --json
```

### Available databases

| Key | Content |
|-----|---------|
| `entretiens` | Interviews and field actions (largest: ~560 pages) |
| `thematiques` | Research themes |
| `segments` | User segments |
| `profils` | User profiles (persona-like) |
| `hypotheses` | Research hypotheses |
| `conclusions` | Validated conclusions |

### Types within entretiens

Verbatim, Observation, Entretien, Terrain, Open Lab, Questionnaire/quanti,
Événement, Note, Retex, Lecture.

## Output format

The script outputs markdown blockquotes ready to embed in your response:

```markdown
> ❝ « La confiance, c'est la base de ce métier. »
> — *Verbatim · 2024-11-06* · [Explorer](/recherche?page=abc123) · [Notion](https://...)
```

## How to integrate citations

Weave citations naturally into your narrative. Don't dump search results — pick the
one or two quotes that best support your point.

**Good:**
> Les données montrent que 45% des candidats en zone rurale ne finalisent pas
> leur inscription. La recherche terrain confirme cette difficulté :
>
> > ❝ « Ici on est très isolés. Le village a été déplacé, il est derrière une
> > bretelle routière et n'a pas accès aux transports en commun. »
> > — *Verbatim · 2025-11-06* · [Explorer](/recherche?page=abc) · [Notion](https://...)

**Bad:**
> Voici 5 résultats de la recherche terrain sur la mobilité :
> 1. ...
> 2. ...

When answering a broad domain question ("what do we know about X?"), you may list
several items as part of a structured narrative — but always with your own synthesis
around them, not as raw search output.

## Exploring further

The full research corpus is browsable at `/recherche` in the web UI.
Link to it when the user might want to explore further:
`[Explorer le corpus terrain](/recherche?q=mobilité)`
