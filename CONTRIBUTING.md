# Contribuer

## Démarrer de zéro

```bash
# 1. Cloner le repo et s'y placer
git clone https://github.com/votre-org/autometa.git
cd autometa

# 2. Lancer Claude Code
claude
```

## Développer une fonctionnalité avec spec-kit

Ce projet utilise [spec-kit](https://github.com/spec-kit/spec-kit) pour piloter la spécification, la planification et l'implémentation des fonctionnalités.

```bash
# 1. Décrivez votre fonctionnalité en français
/speckit.specify "Je veux pouvoir exporter les rapports en PDF"

# 2. Relisez la spec, clarifiez si besoin
/speckit.clarify

# 3. Générez le plan et les tâches
/speckit.plan
/speckit.tasks

# 4. Vérifiez la cohérence (optionnel)
/speckit.analyze

# 5. Lancez l'implémentation
/speckit.implement
```

Les étapes 2-4 sont itératives : revenez à `/speckit.clarify` ou `/speckit.specify` à tout moment.

### Références spec-kit

- **Constitution** : `.specify/memory/constitution.md` — principes et contraintes du projet. Mise à jour via `/speckit.constitution`.
- **Templates** : personnalisables dans `.specify/templates/overrides/` (prioritaires sur les templates de base).
- **Specs** : rangées sous `specs/001-nom-feature/`, créées automatiquement par `/speckit.specify`.
