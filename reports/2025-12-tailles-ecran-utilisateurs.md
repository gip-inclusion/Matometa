---
date: 2026-01-05
website: emplois
original_query: "Quelles sont les tailles d'écran utilisées par les différents types d'utilisateur des Emplois de l'inclusion ?"
query_category: Analyse des équipements utilisateurs
indicator_type:
  - résolution d'écran
  - type d'appareil
  - segmentation utilisateurs
---

# Analyse des tailles d'écran par type d'utilisateur

**Site :** Les Emplois de l'inclusion (emplois.inclusion.beta.gouv.fr)
**Période :** Décembre 2025
**Date d'extraction :** 5 janvier 2026

## Résumé exécutif

L'analyse révèle des **différences majeures** dans les habitudes d'équipement selon le type d'utilisateur :

| Type d'utilisateur | Desktop | Mobile | Visites |
|--------------------|---------|--------|---------|
| Employeurs | **99,7%** | 0,3% | 72 307 |
| Prescripteurs | **99,8%** | 0,2% | 54 755 |
| Demandeurs d'emploi | 28,4% | **71,6%** | 21 501 |
| Anonymes | 61,6% | 38,4% | 249 482 |

**Constat principal :** Les professionnels (employeurs, prescripteurs) travaillent quasi-exclusivement sur ordinateur, tandis que les demandeurs d'emploi utilisent majoritairement leur smartphone.

---

## 1. Répartition desktop/mobile par type d'utilisateur

```
                        Desktop vs Mobile

Employeurs         ████████████████████████████████████████ 99,7%
                   ▏ 0,3%

Prescripteurs      ████████████████████████████████████████ 99,8%
                   ▏ 0,2%

Demandeurs         ███████████▌ 28,4%
d'emploi           ████████████████████████████▌ 71,6%

Anonymes           ████████████████████████▌ 61,6%
                   ███████████████▍ 38,4%

                   ─────────────────────────────────────────
                   0%              50%             100%

                   █ Desktop    █ Mobile (smartphone + tablette)
```

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?idSite=117&period=month&date=2025-12-01&segment=&category=General_Visitors&subcategory=DevicesDetection_Devices) | `DevicesDetection.getType?idSite=117&period=month&date=2025-12-01&segment=dimension1==<user_type>`

---

## 2. Résolutions d'écran par type d'utilisateur (classées par taille)

> **Note :** Les résolutions sont triées par surface d'écran (largeur × hauteur), de la plus grande à la plus petite.

### Employeurs (72 307 visites)

Les employeurs utilisent presque exclusivement des écrans desktop standards :

| Résolution | Surface (px) | Visites | % | Type |
|------------|--------------|---------|---|------|
| **1920x1200** | 2 304 000 | 967 | 1,3% | Desktop |
| **1920x1080** (Full HD) | 2 073 600 | 32 356 | **44,8%** | Desktop |
| 1680x1050 | 1 764 000 | 1 562 | 2,2% | Desktop |
| 1536x960 | 1 474 560 | 1 359 | 1,9% | Desktop (Mac) |
| 1600x900 | 1 440 000 | 2 696 | 3,7% | Desktop |
| **1536x864** | 1 327 104 | 17 378 | **24,0%** | Desktop (scaling) |
| 1440x900 | 1 296 000 | 957 | 1,3% | Desktop |
| 1366x768 | 1 049 088 | 4 239 | 5,9% | Desktop/Laptop |
| 1280x800 | 1 024 000 | 509 | 0,7% | Desktop/Laptop |
| 1280x720 (HD) | 921 600 | 3 532 | 4,9% | Desktop |

```
Employeurs - Résolutions (par taille d'écran ↓)

1920x1200  ██                                      1,3%   (2,3 Mpx)
1920x1080  ████████████████████████████████████  44,8%   (2,1 Mpx)
1680x1050  ███                                     2,2%   (1,8 Mpx)
1536x960   ██                                      1,9%   (1,5 Mpx)
1600x900   █████                                   3,7%   (1,4 Mpx)
1536x864   ███████████████████                    24,0%   (1,3 Mpx)
1440x900   ██                                      1,3%   (1,3 Mpx)
1366x768   ███████                                 5,9%   (1,0 Mpx)
1280x800   █                                       0,7%   (1,0 Mpx)
1280x720   ██████                                  4,9%   (0,9 Mpx)
```

### Prescripteurs (54 755 visites)

Profil très similaire aux employeurs, avec une prédominance de 1536x864 (écrans avec scaling Windows) :

| Résolution | Surface (px) | Visites | % | Type |
|------------|--------------|---------|---|------|
| **1920x1200** | 2 304 000 | 265 | 0,5% | Desktop |
| **1920x1080** | 2 073 600 | 21 931 | **40,1%** | Desktop |
| 1680x1050 | 1 764 000 | 1 228 | 2,2% | Desktop |
| 1536x960 | 1 474 560 | 1 148 | 2,1% | Desktop (Mac) |
| 1600x900 | 1 440 000 | 681 | 1,2% | Desktop |
| **1536x864** | 1 327 104 | 19 111 | **34,9%** | Desktop (scaling) |
| 1280x1024 | 1 310 720 | 319 | 0,6% | Desktop (4:3) |
| 1440x900 | 1 296 000 | 406 | 0,7% | Desktop |
| 1366x768 | 1 049 088 | 1 942 | 3,5% | Desktop/Laptop |
| 1280x800 | 1 024 000 | 1 123 | 2,1% | Desktop/Laptop |
| 1280x720 | 921 600 | 3 988 | 7,3% | Desktop |

```
Prescripteurs - Résolutions (par taille d'écran ↓)

1920x1200  █                                       0,5%   (2,3 Mpx)
1920x1080  ████████████████████████████████      40,1%   (2,1 Mpx)
1680x1050  ██                                      2,2%   (1,8 Mpx)
1536x960   ██                                      2,1%   (1,5 Mpx)
1600x900   █                                       1,2%   (1,4 Mpx)
1536x864   ███████████████████████████           34,9%   (1,3 Mpx)
1280x1024  █                                       0,6%   (1,3 Mpx)
1440x900   █                                       0,7%   (1,3 Mpx)
1366x768   ███                                     3,5%   (1,0 Mpx)
1280x800   ██                                      2,1%   (1,0 Mpx)
1280x720   ██████                                  7,3%   (0,9 Mpx)
```

### Demandeurs d'emploi (21 501 visites)

**Profil radicalement différent** : majorité de résolutions mobiles, grande diversité d'appareils.

| Résolution | Surface (px) | Visites | % | Type |
|------------|--------------|---------|---|------|
| 1920x1080 | 2 073 600 | 1 422 | 6,6% | Desktop |
| 1536x864 | 1 327 104 | 1 197 | 5,6% | Desktop |
| 1366x768 | 1 049 088 | 1 022 | 4,8% | Desktop |
| **414x896** | 370 944 | 957 | 4,5% | **iPhone XR/11** |
| **393x873** | 343 089 | 909 | 4,2% | **Android (Pixel)** |
| **393x852** | 334 836 | 878 | 4,1% | **iPhone 14 Pro** |
| **390x844** | 329 160 | 1 849 | **8,6%** | **iPhone 12/13/14** |
| **384x854** | 328 056 | 761 | 3,5% | **Android** |
| **384x832** | 319 488 | 1 427 | **6,6%** | **Android** |
| **360x800** | 288 000 | 1 063 | **4,9%** | **Android (Samsung)** |

```
Demandeurs d'emploi - Résolutions (par taille d'écran ↓)

DESKTOP:
1920x1080    ███████                        6,6%   (2,1 Mpx)
1536x864     ██████                         5,6%   (1,3 Mpx)
1366x768     █████                          4,8%   (1,0 Mpx)

MOBILE:
414x896  📱  █████                          4,5%   (371 Kpx) iPhone XR/11
393x873  📱  ████                           4,2%   (343 Kpx) Pixel
393x852  📱  ████                           4,1%   (335 Kpx) iPhone 14 Pro
390x844  📱  █████████                      8,6%   (329 Kpx) iPhone 12-14
384x854  📱  ████                           3,5%   (328 Kpx) Android
384x832  📱  ███████                        6,6%   (319 Kpx) Android
360x800  📱  █████                          4,9%   (288 Kpx) Samsung
```

**Observation clé :** La fragmentation est beaucoup plus importante. Les 10 premières résolutions ne représentent que 50% du trafic, contre 90%+ pour les professionnels.

### Visiteurs anonymes (249 482 visites)

Profil mixte reflétant l'ensemble des visiteurs avant connexion :

| Résolution | Surface (px) | Visites | % | Type |
|------------|--------------|---------|---|------|
| 1920x1080 | 2 073 600 | 58 412 | **23,4%** | Desktop |
| 1536x864 | 1 327 104 | 41 866 | **16,8%** | Desktop |
| 1366x768 | 1 049 088 | 9 287 | 3,7% | Desktop |
| 1280x720 | 921 600 | 9 898 | 4,0% | Desktop |
| **414x896** | 370 944 | 6 384 | 2,6% | **Mobile** |
| **393x873** | 343 089 | 5 183 | 2,1% | **Mobile** |
| **393x852** | 334 836 | 5 749 | 2,3% | **Mobile** |
| **390x844** | 329 160 | 12 079 | 4,8% | **Mobile** |
| **384x832** | 319 488 | 8 291 | 3,3% | **Mobile** |
| **360x800** | 288 000 | 6 138 | 2,5% | **Mobile** |

**Data source:** [View in Matomo](https://matomo.inclusion.beta.gouv.fr/index.php?module=CoreHome&action=index&idSite=117&period=month&date=2025-12-01#?idSite=117&period=month&date=2025-12-01&segment=&category=General_Visitors&subcategory=Resolution_Resolutions) | `Resolution.getResolution?idSite=117&period=month&date=2025-12-01&segment=dimension1==<user_type>`

---

## 3. Vue comparative par catégorie de taille

### Desktop (> 900 000 px)

| Résolution | Surface | Employeurs | Prescripteurs | Demandeurs | Anonymes |
|------------|---------|------------|---------------|------------|----------|
| 1920x1200 | 2,3 Mpx | 1,3% | 0,5% | - | 0,5% |
| 1920x1080 | 2,1 Mpx | **44,8%** | **40,1%** | 6,6% | **23,4%** |
| 1680x1050 | 1,8 Mpx | 2,2% | 2,2% | - | 1,4% |
| 1600x900 | 1,4 Mpx | 3,7% | 1,2% | - | 1,9% |
| 1536x864 | 1,3 Mpx | **24,0%** | **34,9%** | 5,6% | **16,8%** |
| 1366x768 | 1,0 Mpx | 5,9% | 3,5% | 4,8% | 3,7% |
| 1280x720 | 0,9 Mpx | 4,9% | 7,3% | 1,6% | 4,0% |

### Mobile (< 500 000 px)

| Résolution | Surface | Appareil type | Employeurs | Prescripteurs | Demandeurs | Anonymes |
|------------|---------|---------------|------------|---------------|------------|----------|
| 414x896 | 371 Kpx | iPhone XR/11 | - | - | 4,5% | 2,6% |
| 393x873 | 343 Kpx | Pixel | - | - | 4,2% | 2,1% |
| 393x852 | 335 Kpx | iPhone 14 Pro | - | - | 4,1% | 2,3% |
| 390x844 | 329 Kpx | iPhone 12-14 | - | - | **8,6%** | **4,8%** |
| 384x832 | 319 Kpx | Android | - | - | **6,6%** | 3,3% |
| 360x800 | 288 Kpx | Samsung | - | - | **4,9%** | 2,5% |

---

## 4. Implications UX/Design

### Points d'attention

1. **Interface professionnelle (employeurs, prescripteurs)**
   - Optimiser pour 1920x1080 et 1536x864 (représentent ~70% du trafic)
   - Les fonctionnalités critiques peuvent supposer un écran desktop
   - Le responsive mobile n'est pas prioritaire pour ces utilisateurs

2. **Interface demandeurs d'emploi**
   - **Mobile-first obligatoire** : 71,6% des visites sur smartphone
   - Tester prioritairement sur iPhone (390x844) et Android (384x832, 360x800)
   - Grande fragmentation des résolutions = importance des tests multi-devices
   - Formulaires de candidature doivent être optimisés pour le pouce

3. **Pages publiques (visiteurs anonymes)**
   - Approche hybride : 38% de mobile
   - Pages d'accueil et de recherche d'offres doivent fonctionner sur les deux
   - Le parcours de création de compte candidat doit être mobile-first

### Recommandations de breakpoints

Basé sur les données réelles d'utilisation :

```css
/* Mobile - Demandeurs d'emploi et visiteurs anonymes */
@media (max-width: 480px) { }  /* Smartphones - 288K-371K px */

/* Tablet - Rare mais existant */
@media (min-width: 481px) and (max-width: 1024px) { }

/* Desktop standard - Écrans ~1 Mpx */
@media (min-width: 1025px) and (max-width: 1536px) { }  /* 1366x768, 1280x720 */

/* Desktop large - Écrans >1.3 Mpx */
@media (min-width: 1537px) { }  /* 1920x1080, 1536x864 (scaling) */
```

---

## 5. Méthodologie et sources

### Requêtes API utilisées

```bash
# Résolutions par type d'utilisateur
curl "https://matomo.inclusion.beta.gouv.fr/?module=API&method=Resolution.getResolution\
&idSite=117&period=month&date=2025-12-01&format=json\
&segment=dimension1==employer&filter_limit=50"

# Types d'appareils par type d'utilisateur
curl "https://matomo.inclusion.beta.gouv.fr/?module=API&method=DevicesDetection.getType\
&idSite=117&period=month&date=2025-12-01&format=json\
&segment=dimension1==job_seeker"
```

### Dimension personnalisée utilisée

- **ID 1 (visit scope) - UserKind** : `prescriber`, `employer`, `job_seeker`, `anonymous`, `labor_inspector`, `itou_staff`

### Période et volume

- **Période :** 1er au 31 décembre 2025
- **Total visites :** 398 250
- **Répartition :** Anonymes 61,5% | Employeurs 18,7% | Prescripteurs 14,1% | Demandeurs 5,6%

---

## Annexe : Données brutes complètes

<details>
<summary>Cliquer pour voir les données brutes (JSON)</summary>

### Type d'appareil global

```json
{
  "Desktop": 288420,
  "Smartphone": 107843,
  "Tablet": 1218,
  "Phablet": 585,
  "Unknown": 176
}
```

### Type d'appareil par utilisateur

```json
{
  "employer": {
    "Desktop": 72127,
    "Smartphone": 169,
    "Tablet": 11
  },
  "prescriber": {
    "Desktop": 54626,
    "Smartphone": 126,
    "Tablet": 2
  },
  "job_seeker": {
    "Smartphone": 15163,
    "Desktop": 6108,
    "Phablet": 125,
    "Tablet": 99
  },
  "anonymous": {
    "Desktop": 153686,
    "Smartphone": 94029,
    "Tablet": 1126,
    "Phablet": 458
  }
}
```

</details>
