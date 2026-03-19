Critères de rejet en revue de code. Si l'un de ces points est violé, la PR ne passe pas.

Intégrité : SQL non paramétré, colonnes dynamiques non validées, migration non idempotente, `SCHEMA_VERSION` non incrémenté.

Sécurité : secrets en dur, `.env` commité, endpoint non authentifié, path traversal possible.

Qualité : code commenté, commentaires descriptifs ou délimiteurs, docstrings verbeuses, duplication non factorisée, tests dupliqués au lieu de `parametrize`, imports ou variables inutilisés, code inatteignable.

Cohérence : pattern divergent sans justification, helper pour un seul usage, abstraction prématurée, gestion d'erreur pour cas impossible.

Tests : code modifié sans test, assertion triviale ou absente, test dépendant d'un état global, intégration sans `@pytest.mark.integration`.

API : instanciation directe de `MatomoAPI`/`MetabaseAPI`, boucle de >5 requêtes segmentées Matomo, appel sans timeout.
