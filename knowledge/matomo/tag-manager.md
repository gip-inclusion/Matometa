# Matomo Tag Manager API

## Concepts essentiels

### Le draft

Chaque container a une version **draft** permanente — c'est le "brouillon de travail".
Son ID est fixe et ne change jamais (ex : version 420 pour Dora_Preprod).

- Toutes les créations/modifications/suppressions d'objets se font **toujours dans le draft**.
- Le draft n'est déployé **nulle part** tant qu'on ne publie pas.
- Récupérer l'ID du draft : `getContainer` → champ `draft.idcontainerversion`.

### Les versions publiées

Quand on publie, Matomo crée une **nouvelle version numérotée** (snapshot du draft à l'instant T)
et la déploie sur l'environnement choisi. Les objets du draft reçoivent de **nouveaux IDs**
dans la version publiée — les IDs du draft et de la version publiée sont différents.

```
draft (v420)              publication              v972 (live)
  trigger 13994    ──────────────────────────→   trigger 14030
  tag     11149    ──────────────────────────→   tag     11170
```

### Les environnements (Dora_Preprod)

| Environnement | Usage |
|---|---|
| `live` | Ce que charge le site preprod par défaut |
| `staging` | Environnement staging dédié |
| `dev` | Développement |
| `production` | (nommage propre à l'équipe) |
| `pentest` | Tests de sécurité |
| `preview` | Preview mode (draft en test) |

---

## Workflow complet : créer → tester → publier → nettoyer

### 1. Trouver le draft

```python
import sys, requests
sys.path.insert(0, '/app')
from lib.query import execute_matomo_query, CallerType

# getContainer retourne le draft dans le champ "draft"
r = execute_matomo_query(instance="inclusion", caller=CallerType.AGENT,
    method="TagManager.getContainer",
    params={"idSite": SITE_ID, "idContainer": CONTAINER_ID})

draft_version_id = r.data["draft"]["idcontainerversion"]
# Vérifier aussi les environnements actuellement déployés :
for rel in r.data["releases"]:
    print(f"  {rel['environment']} → v{rel['idcontainerversion']} par {rel['release_login']}")
```

### 2. Créer un trigger dans le draft

Les écritures nécessitent **POST** (pas GET) avec notation PHP pour les tableaux imbriqués.
Ne pas utiliser `lib.query` pour les opérations d'écriture — utiliser `requests` directement.

```python
import requests
from lib.query import get_matomo

api = get_matomo('inclusion')
BASE_URL = f"https://{api.url}/"
TOKEN = api.token

def matomo_post(method, data):
    payload = {"module": "API", "method": method, "format": "JSON", "token_auth": TOKEN}
    payload.update(data)
    resp = requests.post(BASE_URL, data=payload, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    if isinstance(result, dict) and result.get("result") == "error":
        raise Exception(f"API error: {result.get('message')}")
    return result

# Créer un trigger AllElementsClick avec une condition sur les classes CSS
result = matomo_post("TagManager.addContainerTrigger", {
    "idSite": SITE_ID,
    "idContainer": CONTAINER_ID,
    "idContainerVersion": DRAFT_VERSION_ID,
    "type": "AllElementsClick",
    "name": "Mon trigger",
    "description": "Optionnel",
    # Conditions : notation PHP pour tableaux imbriqués
    "conditions[0][comparison]": "contains",
    "conditions[0][actual]": "ClickClasses",
    "conditions[0][expected]": "ma-classe-css",
    # Conditions supplémentaires :
    # "conditions[1][comparison]": "starts_with",
    # "conditions[1][actual]": "PageUrl",
    # "conditions[1][expected]": "https://monsite.fr/ma-page/",
})
trigger_id = result["value"]  # ID dans le draft
```

**Types de triggers disponibles :** `AllElementsClick`, `AllLinksClick`, `PageView`,
`FormSubmit`, `HistoryChange`, `WindowLoaded`, `ElementVisibility`, `CustomEvent`

**Variables `actual` dans les conditions :**

| Variable | Signification |
|---|---|
| `ClickId` | Attribut `id` de l'élément cliqué |
| `ClickClasses` / `mtm.clickElementClasses` | Classes CSS de l'élément cliqué |
| `ClickDestinationUrl` | URL cible du lien cliqué |
| `ClickText` | Texte visible de l'élément cliqué |
| `ClickElement` | Sélecteur CSS (pour `match_css_selector`) |
| `ClickedElementParentId` | ID du parent de l'élément |
| `PageUrl` | URL complète de la page |
| `PagePath` | Chemin de la page |
| `PageTitle` | Titre de la page |
| `HistoryHashNewUrl` | Nouvelle URL après navigation SPA |
| `HistoryHashOldUrl` | Ancienne URL (détecter un changement) |
| `FormId` | Attribut `id` du formulaire |
| `VisibleElementId` | ID de l'élément visible (ElementVisibility) |
| `VisibleElementText` | Texte visible dans le viewport |
| `loggedIn` | Variable DataLayer personnalisée |

**Opérateurs :**

| API | Sens |
|---|---|
| `equals` | = (insensible à la casse) |
| `equals_exactly` | = (casse exacte) |
| `contains` | contient |
| `starts_with` | commence par |
| `ends_with` | finit par |
| `matches_regex` | expression régulière |
| `is_not_equal` | ≠ |
| `does_not_contain` / `not_contains` | ne contient pas |
| `match_css_selector` | sélecteur CSS |

### 3. Créer un tag CustomHtml dans le draft

```python
fete = "\U0001F389"  # 🎉 — NE PAS utiliser les surrogates \uD83C\uDF89

html_code = f"""<script>
(function() {{
  var el = document.querySelector('.ma-classe-css');
  if (el) {{ el.innerHTML += ' {fete}'; }}
}})();
<\/script>"""

result = matomo_post("TagManager.addContainerTag", {
    "idSite": SITE_ID,
    "idContainer": CONTAINER_ID,
    "idContainerVersion": DRAFT_VERSION_ID,
    "type": "CustomHtml",
    "name": "Mon tag HTML",
    "description": "Optionnel",
    # ⚠️ Le paramètre s'appelle "customHtml", PAS "html"
    "parameters[customHtml]": html_code,
    "parameters[htmlPosition]": "bodyEnd",   # headStart | headEnd | bodyStart | bodyEnd
    # Associer au trigger créé précédemment
    "fireTriggerIds[0]": trigger_id,
    # "blockTriggerIds[0]": autre_trigger_id,  # pour bloquer dans certains cas
    # Valeurs valides de fireLimit :
    "fireLimit": "once_page",   # unlimited | once_page | once_24hours | once_lifetime
    "priority": 999,
    "status": "active",         # active | paused
})
tag_id = result["value"]
```

**Piège emoji :** utiliser `"\U0001F389"` (Python 3 unicode), jamais `"\uD83C\uDF89"`
(surrogate pair UTF-16) — `requests` lève `UnicodeEncodeError: surrogates not allowed`.

### 4. Tester sans publier — le mode preview

Le mode preview charge le **draft** sur le site cible, sans modifier l'environnement live.
Il fonctionne via un cookie posé dans le navigateur.

```python
# Activer le preview (s'applique à la session navigateur courante)
matomo_post("TagManager.enablePreviewMode", {
    "idSite": SITE_ID,
    "idContainer": CONTAINER_ID,
    # "idContainerVersion": DRAFT_VERSION_ID  # optionnel, défaut = draft
})

# Désactiver
matomo_post("TagManager.disablePreviewMode", {
    "idSite": SITE_ID,
    "idContainer": CONTAINER_ID,
})
```

**Pour tester :** après `enablePreviewMode`, visiter le site cible dans le même navigateur.
Le container JS (`container_{CONTAINER_ID}.js`) détecte le cookie et charge le draft.

**URL du container JS (live) :**
```
https://matomo.inclusion.beta.gouv.fr/js/container_{CONTAINER_ID}.js
```

**Code d'embed (à placer dans `<head>`) :**
```html
<!-- Matomo Tag Manager -->
<script>
  var _mtm = window._mtm = window._mtm || [];
  _mtm.push({'mtm.startTime': (new Date().getTime()), 'event': 'mtm.Start'});
  (function() {
    var d=document, g=d.createElement('script'), s=d.getElementsByTagName('script')[0];
    g.async=true; g.src='https://matomo.inclusion.beta.gouv.fr/js/container_XXXX.js';
    s.parentNode.insertBefore(g,s);
  })();
<\/script>
<!-- End Matomo Tag Manager -->
```

Récupérer le code d'embed via API :
```python
r = execute_matomo_query(instance="inclusion", caller=CallerType.AGENT,
    method="TagManager.getContainerEmbedCode",
    params={"idSite": SITE_ID, "idContainer": CONTAINER_ID, "environment": "live"})
print(r.data["value"])
```

### 5. Publier

```python
# Crée une nouvelle version numérotée depuis le draft et la pousse sur l'environnement
matomo_post("TagManager.publishContainerVersion", {
    "idSite": SITE_ID,
    "idContainer": CONTAINER_ID,
    "idContainerVersion": DRAFT_VERSION_ID,
    "environment": "live",   # ou "staging", "dev", etc.
})
```

⚠️ **À savoir :** la publication crée une nouvelle version. Les objets du draft reçoivent
de **nouveaux IDs** dans la version publiée — garder les anciens IDs (draft) pour toute
opération ultérieure sur le draft.

### 6. Vérifier ce qui est déployé

```python
r = execute_matomo_query(instance="inclusion", caller=CallerType.AGENT,
    method="TagManager.getContainer",
    params={"idSite": SITE_ID, "idContainer": CONTAINER_ID})

# Environnements → versions
for rel in r.data["releases"]:
    print(f"  {rel['environment']:<12} → v{rel['idcontainerversion']} ({rel.get('version_name','?')})"
          f" — {rel['release_login']} le {rel['release_date'][:10]}")

# Draft courant
draft = r.data["draft"]
print(f"  draft        → v{draft['idcontainerversion']} (revision {draft['revision']})")
```

### 7. Supprimer des objets

```python
# Supprimer du draft ET de la version publiée
for version_id, tid, label in [
    (DRAFT_VERSION, DRAFT_TRIGGER_ID, "draft"),
    (LIVE_VERSION,  LIVE_TRIGGER_ID,  "live"),
]:
    matomo_post("TagManager.deleteContainerTrigger", {
        "idSite": SITE_ID, "idContainer": CONTAINER_ID,
        "idContainerVersion": version_id, "idTrigger": tid,
    })
    matomo_post("TagManager.deleteContainerTag", {
        "idSite": SITE_ID, "idContainer": CONTAINER_ID,
        "idContainerVersion": version_id, "idTag": tag_id_for_version,
    })
```

**⚠️ Supprimer dans le draft ne retire pas de la version publiée**, et vice versa.
Il faut supprimer dans les deux si on veut nettoyer partout.

---

## Débogage

### Erreur fréquente : `category and action must not be empty`

Cette erreur apparaît dans la console navigateur quand un tag Matomo de type `event`
se déclenche avec `eventCategory` ou `eventAction` vide.

**Causes habituelles :**
1. **Variable DataLayer non résolue** — ex : `eventCategory = {{url}}` où la variable
   `{{url}}` est de type DataLayer mais la clé n'a pas été poussée par l'app au moment du clic.
2. **Trigger sans condition** — un trigger `AllElementsClick` sans aucune condition
   se déclenche sur **tous les clics** de la page, y compris des clics inattendus.

**Comment trouver le tag coupable :**
```python
# Exporter la version live et chercher les tags event suspects
r = execute_matomo_query(instance="inclusion", caller=CallerType.AGENT,
    method="TagManager.exportContainerVersion",
    params={"idSite": SITE_ID, "idContainer": CONTAINER_ID, "idContainerVersion": LIVE_VERSION})

trigger_by_id = {t['idtrigger']: t for t in r.data['triggers']}

for tag in r.data['tags']:
    if tag['type'] != 'Matomo': continue
    p = tag.get('parameters', {})
    if p.get('trackingType') != 'event': continue
    cat = p.get('eventCategory', '')
    action = p.get('eventAction', '')
    # Suspects : vide, ou variable {{...}} qui peut résoudre à vide
    if not cat.strip() or not action.strip() or '{{' in cat or '{{' in action:
        fids = tag.get('fire_trigger_ids', [])
        triggers = [trigger_by_id.get(f, {}) for f in fids]
        # Vérifier si un trigger n'a pas de conditions (fire-all)
        for t in triggers:
            if not t.get('conditions'):
                print(f"⚠️ TAG '{tag['name']}' + TRIGGER '{t['name']}' sans condition → fire-all")
```

### Lire le container déployé

Le fichier JS du container est public et lisible — utile pour vérifier ce qui tourne vraiment :
```
https://matomo.inclusion.beta.gouv.fr/js/container_{CONTAINER_ID}.js
```
La variable `cb=` dans l'URL correspond au numéro de révision.

### Identifier l'environnement qui tourne

La stack trace dans la console indique le nom du fichier container :
```
container_xg8aydM9.js   → container xg8aydM9, donc site 210 (Dora_Preprod)
```

---

## Méthodes d'écriture

| Méthode | Paramètres clés |
|---|---|
| `addContainerTrigger` | `idSite, idContainer, idContainerVersion, type, name, conditions[N][comparison/actual/expected]` |
| `updateContainerTrigger` | idem + `idTrigger` |
| `deleteContainerTrigger` | `idSite, idContainer, idContainerVersion, idTrigger` |
| `addContainerTag` | `idSite, idContainer, idContainerVersion, type, name, parameters[...], fireTriggerIds[N], fireLimit, status` |
| `updateContainerTag` | idem + `idTag` |
| `deleteContainerTag` | `idSite, idContainer, idContainerVersion, idTag` |
| `pauseContainerTag` | `idSite, idContainer, idContainerVersion, idTag` |
| `resumeContainerTag` | `idSite, idContainer, idContainerVersion, idTag` |
| `publishContainerVersion` | `idSite, idContainer, idContainerVersion, environment` |
| `enablePreviewMode` | `idSite, idContainer, idContainerVersion?` |
| `disablePreviewMode` | `idSite, idContainer` |

**Valeurs valides de `fireLimit` :** `unlimited`, `once_page`, `once_24hours`, `once_lifetime`

**Valeurs valides de `htmlPosition` (CustomHtml) :** `headStart`, `headEnd`, `bodyStart`, `bodyEnd`

---

## Structure des données

### Container (`getContainers`)

```json
{
  "idcontainer": "xg8aydM9",
  "name": "Dora_Preprod",
  "context": "web",
  "status": "active",
  "idsite": 210
}
```

### `getContainer` — la réponse la plus complète

```json
{
  "idcontainer": "xg8aydM9",
  "draft": {
    "idcontainerversion": 420,
    "revision": 0
  },
  "releases": [
    { "environment": "live", "idcontainerversion": 972,
      "version_name": "0.0.111111", "release_login": "user.name",
      "release_date": "2026-03-16 10:22:36" }
  ]
}
```

### Trigger

```json
{
  "idtrigger": 14030,
  "type": "AllElementsClick",
  "name": "Clic élément orange",
  "conditions": [
    { "comparison": "contains", "actual": "ClickClasses", "expected": "bg-service-orange" }
  ],
  "parameters": []
}
```

### Tag

```json
{
  "idtag": 11170,
  "type": "CustomHtml",
  "name": "Emoji fete sur clic orange",
  "status": "active",
  "parameters": {
    "customHtml": "<script>...<\/script>",
    "htmlPosition": "bodyEnd"
  },
  "fire_trigger_ids": [14030],
  "block_trigger_ids": [],
  "fire_limit": "once_page",
  "priority": 999,
  "fire_delay": 0,
  "start_date": null,
  "end_date": null
}
```

**Types de tags :**

| Type | Paramètres principaux |
|---|---|
| `Matomo` | `matomoConfig`, `trackingType` (pageview/event/goal), `eventCategory`, `eventAction`, `eventName`, `eventValue`, `documentTitle`, `customUrl`, `customDimensions` |
| `CustomHtml` | `customHtml` ⚠️ (pas `html`), `htmlPosition` |
| `LinkedinInsight` | (aucun paramètre visible) |

---

## État du Tag Manager par site (2026-03-16)

| Site | ID | Container ID | Triggers actifs | Tags | Variables |
|------|----|-------------|---------|------|-----------|
| Emplois | 117 | oBBrLa4S | 1 (sans tag) | 0 | 0 |
| Marché | 136 | RBvmJtrU | 57 | 57 | 1 |
| Pilotage | 146 | czDcW7tH | 6 | 4 | 1 |
| Communauté | 206 | GTln5jDH | 3 | 3 | 1 |
| Dora prod | 211 | 1y35glgB | 69 | 55 | 22 |
| Plateforme | 212 | SAGWfnKo | 14 | 13 | 1 |
| RDV-Insertion | 214 | DxfPtj4z | 21 | 19 | 5 |
| Mon Recap | 217 | tBXCnpOZ | 4 | 3 | 1 |
| Dora preprod | 210 | xg8aydM9 | 36 | 21 | 19 |

**Emplois** n'utilise pas MTM au 2026-03-16 : tracking natif dans les templates Django.
La recette des Emplois (site 220) 

---

## Performance

- `exportContainerVersion` : ~0,1s par site
- Scan complet 8 sites + preprod (27 appels, séquentiel) : **~3s**
- En parallèle : estimé < 0,5s
- Opérations d'écriture (POST) : < 0,5s chacune
- → Temps réel possible ; cache journalier recommandé (les containers changent peu).

---

> Exploré et testé le 2026-03-16 — création, publication, suppression de triggers et tags
> vérifiés en conditions réelles sur Dora_Preprod (site 210, container `xg8aydM9`).