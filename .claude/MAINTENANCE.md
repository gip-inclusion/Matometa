# Journal de maintenance

Tâches récurrentes à exécuter périodiquement.

| Tâche | Cadence | Dernier run | Prochain dû | Notes |
|---|---|---|---|---|
| Audit vulnérabilités (`make security`) | Mensuel | — | — | bandit + pip-audit |
| Sync inventaire Metabase | Hebdo | — | — | `sync_metabase --all` |
| Sync fiches sites knowledge | Mensuel | — | — | skill `sync_sites` |
| Sync corpus recherche Notion | Mensuel | — | — | `scripts/sync_notion_research.py` + embed |
| Nettoyage conversations terminées | Trimestriel | — | — | Archiver les conversations >90j |
| Revue des rapports orphelins | Trimestriel | — | — | Rapports sans conversation liée |
| Mise à jour dépendances (`uv lock --upgrade`) | Mensuel | — | — | Suivi des breaking changes |
| Revue dette technique | Trimestriel | — | — | Lancer l'agent `tech-debt` |
| Vérification cohérence knowledge/code | Trimestriel | — | — | Les fiches sites matchent-elles la réalité ? |
