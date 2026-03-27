Ne jamais écrire de commentaires qui expliquent **ce que** fait le code, ni des marqueurs de sections. Le code doit être lisible seul. Exceptions : contexte métier ou contrainte externe non évidente, `# Why:` quand l’intention n’est pas déductible, lien vers une issue, `# noqa` justifié.

Ne jamais générer de code commenté. Si du code n'est plus utile, le supprimer.

Docstrings : une ligne maximum. Pas de Args/Returns/Examples. Les exemples vont dans les tests.

Toujours générer le code le plus court et le plus simple possible. Éviter toute duplication : avant d'écrire du code, vérifier qu'une fonction existante ne fait pas déjà le travail. Trois occurrences similaires = extraction obligatoire.

Pas d'abstractions pour un seul usage, pas de paramètres "au cas où", pas de gestion d'erreur pour des cas impossibles, pas de feature flags sans besoin.

Constantes nommées : ne pas en introduire une si elle n'est référencée qu'une seule fois — inliner la valeur. Pour les « magic values » peu évidentes (URL externe, identifiant tiers, seuil métier, limite API), un commentaire court au-dessus de la ligne suffit ; pas besoin de commenter des littéraux déjà explicites dans le contexte.

Respecter les patterns du fichier et du module. Ne pas introduire un nouveau pattern sans raison. Nommage en français pour le domaine métier, en anglais pour le code technique.

Ne jamais détailler l'implémentation dans les spécifications (CLAUDE.md, SKILL.md, knowledge, rules). Décrire le quoi et le pourquoi, pas le comment. Le code source est la référence pour l'implémentation.

Messages de commit en anglais, concis. Ne pas commiter ni pousser sauf demande explicite.

Ne lancer `make test` et `make lint` que quand des fichiers Python (`.py`) sont modifiés. Ne pas les lancer pour des modifications de fichiers Markdown, de skills, de knowledge, de configuration YAML, ou de documentation.
