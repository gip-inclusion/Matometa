Ne pas instancier `MatomoAPI` ou `MetabaseAPI` directement. Passer par `lib.query.execute_matomo_query` / `execute_metabase_query` (logging, timeouts, signaux d'observabilité inclus).

Segments Matomo : lents (30-180s par mois). Ne jamais boucler sur plus de 5 requêtes segmentées séquentielles. Privilégier les date ranges sans segment.

Tout appel API doit avoir un timeout explicite.
