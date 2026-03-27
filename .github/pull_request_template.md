<!--
  Titre de la PR : en français, concis (idéalement aligné sur le premier commit ou le résumé des changements).
-->

[Lien vers le ticket Notion associé]()

## Pourquoi ?

> _Problème ou besoin adressé, objectifs métier ou techniques visés par ces changements._

## Comment ? <!-- optionnel -->

> _Solution retenue, points d’attention (architecture, choix de conception, limites connues)._

### Check-list générale

* [ ] La description et les spécifications pertinentes sont **en français**.
* [ ] Le **titre de la PR est en français**.
* [ ] Mes commits suivent les [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) : `<type>(<scope optionnel>): <description>`
  * Types courants : `feat`, `fix`, `chore`, `docs`, `refactor`, `test`, etc.
  * Scopes possibles (à adapter) : `web`, `lib`, `skills`, `knowledge`, `config`, `scripts`, `tests`, `ci`
* [ ] Ma branche respecte la convention de nommage `<auteur>/<type>/<feature>`
* [ ] Les **messages de commit sont en anglais** (convention du dépôt — voir `.claude/rules/code.md`).
* [ ] Je me suis relu ; je suis **raisonnablement confiant** que le changement est **minimal** et ciblé
* [ ] J’ai exécuté **`make ci`** avant d’ouvrir la PR lorsque j’ai touché du **Python** (`web/`, `lib/`, `scripts/`, `tests/`). *(Pour du markdown, skills, knowledge ou YAML uniquement, ce n’est pas obligatoire — voir `CLAUDE.md` / `.claude/rules/code.md`.)*
* [ ] J’ai indiqué le ticket Notion associé (ou « N/A » si volontairement absent).
* [ ] J’ai passé le ticket Notion en **review** lorsqu’un ticket existe.

### Si la PR touche du **code Python**

* [ ] J’ai lancé les **tests** pertinents (`make test`) et ajouté ou adapté des **tests** si le comportement est nouveau ou régressif.
* [ ] Pas de secrets ni de données sensibles dans le diff (la CI exécute notamment **gitleaks**).

### Si la PR touche les **skills** (`.claude/skills/`) ou la **knowledge** (`knowledge/`)

* [ ] Les instructions restent au niveau **quoi / pourquoi** ; pas de copier-coller d’implémentation détaillée (voir `.claude/rules/code.md`).

### Si la PR touche **Matomo**, **Metabase**, la **config des sources** ou des **requêtes d’analyse**

* [ ] J’ai vérifié la **cohérence** avec `config/sources.yaml` et les fiches `knowledge/` concernées.
* [ ] Pour des changements d’extraction ou de scripts de sync : j’ai documenté ou testé le **parcours minimal** (commande, périmètre, risque de lenteur côté Matomo si segmenté — voir `CLAUDE.md`).

## Comment tester que ça marche ?

> _Commandes, profil d’environnement (`.env`), parcours manuel, URL locale ou jetable. Si la CI suffit, l’indiquer._

## Captures d’écran <!-- optionnel -->

<!-- UI, Metabase, Matomo, ou sorties pertinentes. -->
