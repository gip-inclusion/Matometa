Toujours utiliser des placeholders paramétrés (`?`, converti en `%s` par `ConnectionWrapper`). Ne jamais interpoler de valeurs dans le SQL.

Colonnes dynamiques : passer par `_build_update_clause` avec validation contre `VALID_*_COLUMNS`. Ne jamais construire de SQL avec des noms de colonnes issus de l'extérieur sans validation.

Migrations dans `web/schema.py`. Chaque migration est idempotente. Incrémenter `SCHEMA_VERSION` après ajout.
