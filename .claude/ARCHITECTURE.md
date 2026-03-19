# Architecture

## Vue d'ensemble

FastAPI single-worker avec ProcessManager in-process. Le PM et le SSE partagent un `SignalRegistry` en mémoire — plusieurs workers casseraient cette communication.

## Couches

**`web/`** — Application FastAPI, routes, templates Jinja2, SSE, ProcessManager. Dépend de `lib/`.

**`lib/`** — Clients API Matomo et Metabase, interface de requête unifiée, observabilité. Ne connaît pas FastAPI.

**`skills/`** — Capacités agent. Chaque skill a un `SKILL.md` et un `scripts/`.

**`knowledge/`** — Base de connaissances markdown, structurée par domaine.

**`config/`** — Configuration des sources de données (`sources.yaml`, substitution `${env.VAR}`).

## Flux principaux

**Conversation** : POST message → DB (pm_commands) → PM poll → spawn agent CLI (stream-json) → parse events → persist en DB → signal SSE → navigateur.

**Requête API** : Agent exécute Python → `lib.query.execute_*_query()` → client API avec retry → signal d'observabilité sur stdout → PM parse → DB.

**Recherche sémantique** : Query → DeepInfra (embedding) → cosine similarity sur ~1700 chunks en cache mémoire (simsimd) → dedup par page → JSON.

## Déploiement

| Environnement | DB | Stockage |
|---|---|---|
| Local | SQLite | Filesystem |
| Docker | PostgreSQL | S3 (MinIO) |
| Scalingo | PostgreSQL addon | S3 (Scaleway) |
