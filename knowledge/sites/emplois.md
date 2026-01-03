# Emplois

- URL: https://emplois.inclusion.beta.gouv.fr
- Matomo site ID: 117
- GitHub: https://github.com/gip-inclusion/les-emplois

## Traffic Baselines (2025)

Data retrieved 2026-01-03 via Matomo API.

### Monthly Visitor Stats

| Month   | Unique Visitors | Visits    | Daily Avg Visitors | Daily Avg Visits |
|---------|-----------------|-----------|--------------------|-----------------:|
| 2025-01 | 189,083         | 460,201   | 6,099              | 14,845           |
| 2025-02 | 177,970         | 434,333   | 6,356              | 15,512           |
| 2025-03 | 188,675         | 466,830   | 6,086              | 15,059           |
| 2025-04 | 187,006         | 447,922   | 6,234              | 14,931           |
| 2025-05 | 165,132         | 391,514   | 5,327              | 12,629           |
| 2025-06 | 175,318         | 425,531   | 5,844              | 14,184           |
| 2025-07 | 169,339         | 424,698   | 5,463              | 13,700           |
| 2025-08 | 155,529         | 339,390   | 5,017              | 10,948           |
| 2025-09 | 219,810         | 526,170   | 7,327              | 17,539           |
| 2025-10 | 221,726         | 545,370   | 7,152              | 17,593           |
| 2025-11 | 189,674         | 452,497   | 6,322              | 15,083           |
| 2025-12 | 167,571         | 398,250   | 5,406              | 12,847           |

**Typical range:** 5,000-7,500 unique visitors/day, 11,000-17,500 visits/day.

**Seasonal patterns:**
- Peak: September-October (rentrée)
- Low: August (summer holidays), May (bridge holidays), December (year-end)

### User Type Distribution (visits)

| Month   | prescriber | employer  | job_seeker | anonymous  | labor_inspector | itou_staff |
|---------|------------|-----------|------------|------------|-----------------|------------|
| 2025-01 | 63,710     | 91,138    | 24,197     | 280,748    | 245             | 160        |
| 2025-02 | 58,804     | 87,988    | 22,849     | 264,333    | 272             | 87         |
| 2025-03 | 60,539     | 96,849    | 25,378     | 283,548    | 367             | 139        |
| 2025-04 | 59,798     | 90,260    | 25,075     | 272,379    | 267             | 134        |
| 2025-05 | 49,333     | 79,116    | 22,347     | 240,363    | 199             | 115        |
| 2025-06 | 57,417     | 87,870    | 21,972     | 257,911    | 235             | 123        |
| 2025-07 | 59,983     | 89,411    | 21,503     | 253,321    | 359             | 119        |
| 2025-08 | 42,829     | 63,929    | 18,365     | 213,971    | 218             | 77         |
| 2025-09 | 68,947     | 102,636   | 27,321     | 326,291    | 815             | 141        |
| 2025-10 | 73,892     | 102,533   | 30,760     | 337,149    | 604             | 152        |
| 2025-11 | 61,538     | 82,199    | 26,756     | 281,392    | 427             | 173        |
| 2025-12 | 56,347     | 74,509    | 22,111     | 244,814    | 362             | 107        |

### User Type Proportions (baseline)

Based on December 2025 (representative month):

| User Type       | Visits  | % of total |
|-----------------|---------|------------|
| anonymous       | 244,814 | 61.5%      |
| employer        | 74,509  | 18.7%      |
| prescriber      | 56,347  | 14.1%      |
| job_seeker      | 22,111  | 5.6%       |
| labor_inspector | 362     | 0.1%       |
| itou_staff      | 107     | <0.1%      |

**Key ratio:** Employers outnumber prescribers ~1.3:1 site-wide.

This baseline is essential for comparing feature-specific usage. For example, if a feature shows prescribers > employers, that feature is disproportionately used by prescribers relative to the site average.

## Custom Dimensions

| ID | Index | Scope  | Name                 | Notes                           |
|----|-------|--------|----------------------|---------------------------------|
| 1  | 1     | visit  | UserKind             | prescriber, employer, job_seeker, anonymous, labor_inspector, itou_staff |
| 2  | 2     | visit  | Unused               | Inactive                        |
| 3  | 1     | action | UserOrganizationKind | FT, ACI, AI, ML, EI, ETTI, etc. |
| 4  | 2     | action | UserDepartment       | French département number (01-976) |

Query visit-scoped dimensions with `idDimension=1`.
Query action-scoped dimensions with `idDimension=3` (org) or `idDimension=4` (dept).

## Matomo Events

Scraped from codebase 2026-01-03. ~108 events tracked.

### Implementation

- **Template tag:** `{% matomo_event "category" "action" "name" %}`
- **JS handler:** `/itou/static/js/matomo.js` - catches clicks on `data-matomo-*` elements
- **Context processor:** sets custom dimensions (user kind, org kind, department)

### Event Categories

#### candidature (47 events)
Core application workflow. Most important category.

| Action | Name | Description |
|--------|------|-------------|
| clic | start_application | User starts a job application |
| clic | postuler-pour-ce-candidat | Prescriber applies on behalf of candidate |
| clic | accept_application | Employer accepts application |
| clic | refuse_application | Employer refuses application |
| clic | postpone_application | Employer postpones decision |
| submit | accept_application_confirmation | Confirms acceptance |
| submit | processing_application | Submits processing action |
| clic-onglet | informations-generales | Views general info tab |
| clic-onglet | appointments | Views appointments tab |
| clic-onglet | historique | Views history tab |
| clic | proposer-rdv | Proposes appointment |
| clic | ajout-commentaire-sidebar | Adds comment |
| exports | export-siae | SIAE exports applications |
| exports | export-prescripteur | Prescriber exports applications |
| submit | batch-*-submit | Batch operations (process, archive, refuse, etc.) |

#### employeurs (16 events)
Employer dashboard and company management.

| Action | Name | Description |
|--------|------|-------------|
| clic | structure-presentation | Views company presentation |
| clic | modifier-infos-entreprise | Edits company info |
| clic | voir-liste-candidatures | Views received applications |
| clic | voir-liste-agrements | Views PASS IAE approvals |
| clic | voir-liste-fiches-salaries | Views ASP employee records |
| clic | creer-fiche-de-poste | Creates job description |
| clic | declarer-embauche | Declares a hire |

#### connexion (7 events)
Authentication flows.

| Action | Name | Description |
|--------|------|-------------|
| clic | se-connecter-avec-pro-connect | ProConnect login |
| clic | se-connecter-avec-pe | France Travail (ex-Pôle emploi) login |
| clic | se-connecter-avec-france-connect | FranceConnect login |

#### inscription-candidat
Job seeker registration.

| Action | Name | Description |
|--------|------|-------------|
| clic | je-n-ai-pas-d-adresse-email | No email option |
| clic | creer-un-compte-candidat | Create account CTA |

#### prescribers (4 events)
Prescriber organization management.

| Action | Name | Description |
|--------|------|-------------|
| clic | organisation-presentation | Views org presentation |
| clic | gerer-collaborateurs | Manages team members |

#### gps (6 events)
GPS referral network feature.

| Action | Name | Description |
|--------|------|-------------|
| clic | displayed_member_phone | Shows member phone |
| clic | copied_user_email | Copies user email |
| clic | consulter_fiche_candidat | Views candidate file |

#### dashboard (4 events)
Main dashboard navigation.

| Action | Name | Description |
|--------|------|-------------|
| clic-onglet | vue-d-ensemble | Overview tab |
| clic-onglet | statistiques | Statistics tab |
| clic | candidats-sans-solution | Views stalled candidates |

#### salaries (4 events)
Employee/contract management.

| Action | Name | Description |
|--------|------|-------------|
| clic | details-salarie | Views employee details |
| clic | edit_jobseeker_infos | Edits job seeker info |

#### help (7 events)
Documentation and support links.

| Action | Name | Description |
|--------|------|-------------|
| clic | footer_documentation | Footer doc link |
| clic | header_documentation | Header doc link |
| clic | zendesk_form | Support contact form |

#### offcanvasNav
Mobile/sidebar navigation clicks. All use `clic` action with menu item names:
- mes-candidatures, candidatures, candidatures-envoyees
- salaries-pass-iae, fiches-salaries-asp
- structure-presentation, metiers-recrutement
- collaborateurs, etc.

#### recherche (2 events)
Search functionality.

| Action | Name | Description |
|--------|------|-------------|
| clic | enregistrer-une-recherche | Saves search |
| clic | clic-sur-recherche-enregistree | Uses saved search |

### Dynamic Event Patterns

Several events use dynamic names constructed at runtime:

#### Category: `connexion {account_type}`
Built from `MATOMO_ACCOUNT_TYPE` enum in `itou/users/enums.py`:
- `connexion prescripteur` (44k events/month)
- `connexion employeur inclusif` (38k events/month)

Template: `{% matomo_event "connexion "|add:matomo_account_type "clic" "..." %}`

#### Name: `voir-liste-candidatures-{status}`
Dashboard links append status name:
- `voir-liste-candidatures-À traiter` (32k)
- `voir-liste-candidatures-En attente` (4k)
- `voir-liste-candidatures-Vivier`

Template: `{% matomo_event "employeurs" "clic" "voir-liste-candidatures-"|add:category.name %}`

#### Name: `candidature_{user_kind}`
Application submission appends user type:
- `candidature_prescripteur` (31k) - prescriber submitting for candidate
- `candidature_candidat` (7k) - job seeker submitting themselves

Template: `matomo_name="candidature_"|add:request.user.get_kind_display`

#### Multi-step wizard: `batch-refuse-application-{step}-submit`
Refuse wizard fires per step:
- `batch-refuse-application-reason-submit` (11k)
- `batch-refuse-application-job-seeker-answer-submit` (11k)
- `batch-refuse-application-prescriber-answer-submit` (9k)

Code: `matomo_event_name = f"batch-refuse-application-{self.step}-submit"`

### Additional Categories (from Matomo Dec 2025)

| Category | Events | Description |
|----------|--------|-------------|
| fiches-salarié | 8k | Employee record creation (ASP). Uses `création` event. |
| modale-nouveautes | 9k | News modal popup |
| compte-candidat | 4k | Job seeker account creation |
| nir-temporaire | 1k | Temporary NIR (social security) skip |
| partners | 2k | External partner links (Diagoriente) |
| telechargement-pdf | 241 | PDF downloads (PASS IAE) |
| employers | 696 | English variant (legacy?) |
| salarie | 94 | Singular variant (legacy?) |

### Notes

- French/English mix: `employeurs` vs `employers`, `salaries` vs `salarie`
- Accents preserved: `fiches-salarié`, `À traiter`, `création`
- Top events by volume: `clic-metiers` (83k), `se-connecter-avec-pro-connect` (83k), `start_application` (62k)
