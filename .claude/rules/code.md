Imports : tout regrouper en tête de module (stdlib, puis tiers, puis paquet local), dans l’ordre attendu par le linter. Ne pas utiliser d’imports différés dans des fonctions ou des blocs `if` sauf cas documenté où c’est indispensable (dépendance circulaire qu’on ne peut pas résoudre autrement, coût de chargement prohibitive pour un module optionnel rarement utilisé, etc.). Les agents ne doivent pas introduire d’imports lazy « par habitude ».

Préfixe `_` : un nom `_*` est **volontairement privé** au sens où il ne doit être ni importé ni appelé depuis un autre module (les tests ne devraient pas s’y accéder non plus). Ce cas doit rester **rare**. Ne pas préfixer tout le monde d’un `_` « par habitude ». Réserver **fonctions imbriquées / fermetures / lambdas** aux cas où elles servent vraiment à lier des variables du scope englobant ; sinon préférer des fonctions au niveau module (sans `_` si ce ne sont pas des symboles privés intentionnels) et un `__all__` explicite si besoin de limiter l’export.

Ne jamais écrire de commentaires qui expliquent **ce que** fait le code, ni des marqueurs de sections. Le code doit être lisible seul. Exceptions : contexte métier ou contrainte externe non évidente, `# Why:` quand l’intention n’est pas déductible, lien vers une issue, `# noqa` justifié.

Ne jamais générer de code commenté. Si du code n'est plus utile, le supprimer.

Docstrings : une ligne maximum. Pas de Args/Returns/Examples. Les exemples vont dans les tests.

Toujours générer le code le plus court et le plus simple possible. Éviter toute duplication : avant d'écrire du code, vérifier qu'une fonction existante ne fait pas déjà le travail. Trois occurrences similaires = extraction obligatoire.

Pas d'abstractions pour un seul usage, pas de paramètres "au cas où", pas de gestion d'erreur pour des cas impossibles, pas de feature flags sans besoin.

Respecter les patterns du fichier et du module. Ne pas introduire un nouveau pattern sans raison. Nommage en français pour le domaine métier, en anglais pour le code technique.

Ne jamais détailler l'implémentation dans les spécifications (CLAUDE.md, SKILL.md, knowledge, rules). Décrire le quoi et le pourquoi, pas le comment. Le code source est la référence pour l'implémentation.

Messages de commit en anglais, concis. Ne pas commiter ni pousser sauf demande explicite.

Ne lancer `make test` et `make lint` que quand des fichiers Python (`.py`) sont modifiés. Ne pas les lancer pour des modifications de fichiers Markdown, de skills, de knowledge, de configuration YAML, ou de documentation.
