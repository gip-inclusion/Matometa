---
title: Corpus terrain (Notion)
cron: false
schedule: weekly
timeout: 1200
---

Désactivé sur Scalingo : le cron tourne sur un dyno one-off éphémère, le
fichier SQLite produit n'est jamais visible par le dyno web. Le refresh
se fait en local (`scripts/refresh_research.py`) puis upload vers S3
(`s3://matometa/data/notion_research.db`). Le dyno web télécharge le DB
depuis S3 au démarrage (voir `web/app.py` lifespan).
