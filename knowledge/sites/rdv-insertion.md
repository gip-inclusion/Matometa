# RDV-Insertion

- URL: https://www.rdv-insertion.fr
- Matomo site ID: 214
- GitHub: https://github.com/gip-inclusion/rdv-insertion
- Metabase: [RDVI instance](../rdvi/README.md) — business data (invitations, RDVs, departments, organisations)

## Traffic Baselines (2025)

Data retrieved 2026-01-06 via Matomo API.

### Monthly Visitor Stats

| Month   | Unique Visitors | Visits    | Daily Avg Visitors | Daily Avg Visits |
|---------|-----------------|-----------|--------------------|-----------------:|
| 2025-01 |           3,962 |    14,648 |                128 |              473 |
| 2025-02 |           3,563 |    13,617 |                127 |              486 |
| 2025-03 |           4,013 |    15,739 |                129 |              508 |
| 2025-04 |           3,874 |    14,954 |                129 |              498 |
| 2025-05 |           2,556 |     8,851 |                 82 |              286 |
| 2025-06 |               4 |         5 |                  0 |                0 |
| 2025-07 |           2,542 |    11,264 |                 82 |              363 |
| 2025-08 |             820 |     6,499 |                 26 |              210 |
| 2025-09 |           1,043 |     8,738 |                 35 |              291 |
| 2025-10 |             980 |     8,979 |                 32 |              290 |
| 2025-11 |             877 |     8,091 |                 29 |              270 |
| 2025-12 |             923 |     7,784 |                 30 |              251 |

**Typical range:** 0-129 unique visitors/day, 0-508 visits/day.

### Engagement Metrics

| Month   | Bounce Rate | Actions/Visit | Avg Time on Site |
|---------|-------------|---------------|------------------|
| 2025-01 |         27% |          13.8 |          12m 09s |
| 2025-02 |         26% |          14.3 |          12m 58s |
| 2025-03 |         23% |          20.8 |          13m 28s |
| 2025-04 |         22% |          23.9 |          14m 07s |
| 2025-05 |         23% |          25.1 |          13m 31s |
| 2025-06 |         80% |           1.2 |               1s |
| 2025-07 |         19% |          27.8 |          14m 18s |
| 2025-08 |          5% |          23.7 |          15m 46s |
| 2025-09 |          5% |            21 |          15m 03s |
| 2025-10 |          5% |          20.6 |          15m 10s |
| 2025-11 |          4% |          21.7 |          15m 52s |
| 2025-12 |          5% |            21 |          15m 10s |

## Custom Dimensions

No custom dimensions configured for this site.

## Saved Segments

*Retrieved 2026-01-06 via Matomo API.*

| Name | Definition |
|------|------------|
| CONTENT - page Sign in | `pageUrl=@https%253A%252F%252Fwww.rdv-insertion.fr%252Fsig...` |
| DEVICE - mobile | `deviceType==smartphone` |
| PROFILE - Logged in | `pageUrl=@https%253A%252F%252Fwww.rdv-insertion.fr%252Forg...` |
| RETENTION - dernière visite 30j | `daysSinceLastVisit<32;daysSinceLastVisit>=1` |
| RETENTION - dernière visite 30j - Connectés | `daysSinceLastVisit<32;pageUrl=@https%253A%252F%252Fwww.rd...` |

## Matomo Events

Data retrieved 2026-01-03 from both Matomo API and GitHub codebase analysis.

### Implementation

RDV-Insertion uses Matomo Tag Manager (MTM) for event tracking, not the standard Matomo JS tracker.

- **Tag Manager Container:** Loaded via `MATOMO_CONTAINER_ID` environment variable
- **Controller:** `app/javascript/controllers/matomo_script_tag_controller.js` - initializes MTM
- **Tracking consent:** Only enabled for logged-in agents who have accepted tracking (`tracking_accepted?`)
- **URL anonymization:** Route patterns replace IDs (e.g., `/organisations/:id/users` instead of `/organisations/123/users`)
- **Event binding:** Uses HTML element IDs prefixed with `rdvi_` or standard button IDs

### Event Actions (Dec 2025)

Most events use the page URL as category and an action identifier. Top events by volume:

| Action | Events | Description |
|--------|--------|-------------|
| Chargement du fichier | 46,991 | File upload processing (Upload category) |
| confirm-button | 2,697 | Confirmation modal clicks |
| archive-button | 2,392 | Archive user clicks |
| rdvi_header_organisation-nav | 2,519 | Organisation navigation dropdown |
| toggle-rdv-status | 2,208 | Toggle appointment status |
| rdvi_index-nav_filter-status-button | 1,492 | Status filter button |
| rdvi_index-nav_create-one-user | 702 | Create single user button |
| rdvi_index-nav_filter-referent-button | 637 | Referent filter button |
| Vues | 336 | Page Configuration views |

### Event Categories

Events are categorized primarily by page URL pattern:

| Category Pattern | Description |
|------------------|-------------|
| `Upload` | File upload processing events |
| `Page Configuration` | Configuration page views |
| `/organisations/{id}/users` | Organisation user list actions |
| `/departments/{id}/users` | Department user list actions |
| `Others` | Uncategorized events |

### UI Element Events (rdvi_ prefix)

Events tracked via HTML element IDs in ERB templates:

#### Header Navigation
- `rdvi_header_organisation-nav` - Organisation switcher dropdown
- `rdvi_header_help-center` - Help menu button
- `rdvi_header_log-out` - Logout link
- `rdvi_header_redirection` - Logo/home link

#### User List Actions
- `rdvi_index-nav_filter-status-button` - Status filter dropdown
- `rdvi_index-nav_filter-referent-button` - Referent filter dropdown
- `rdvi_index-nav_filter-tags-button` - Tags filter dropdown
- `rdvi_index-nav_filter-orientation-type-button` - Orientation type filter
- `rdvi_index-nav_filter-creation-date` - Creation date filter
- `rdvi_index-nav_create-one-user` - Create single user button
- `rdvi_index-nav_upload-users` - Upload users button
- `rdvi_index-nav_redirect-rdvs` - RDV-Solidarites link
- `csvExportButton` - CSV export dropdown

#### Upload Workflow (file selection)
- `rdvi_upload_select-category_validate` - Validate category selection
- `rdvi_upload_select-category_back` - Back from category selection
- `rdvi_upload_select-file_file-choice` - File picker label
- `rdvi_upload_select-file_validate` - Validate file selection
- `rdvi_upload_select-file_delete` - Remove selected file
- `rdvi_upload_select-file_change-file` - Change selected file
- `rdvi_upload_select-file_back` - Back from file selection
- `rdvi_upload_select-file_drag-drop` - Drag-and-drop file (JS)

#### Upload Workflow (user data)
- `rdvi_upload_users-data_all-select` - Select all users checkbox
- `rdvi_upload_users-data_user-select-{id}` - Select individual user
- `rdvi_upload_users-data_create-folder` - Create/update folders button
- `rdvi_upload_users-data_pass-invit` - Skip to invitations
- `rdvi_upload_users-data_end-course` - End workflow
- `rdvi_upload_users-data_all-data-user` - View all users tab
- `rdvi_upload_users-data_data-user-error` - View error users tab
- `rdvi_upload_users-data_folder-error` - Folder error tab
- `rdvi_upload_users-data_data-complete` - Complete data with CNAF
- `rdvi_upload_users-data_open-folder-user-{id}` - Open user folder
- `rdvi_upload_users-data_return` - Return to previous step
- Sort buttons: `*_first-name_sort`, `*_last-name_sort`, `*_folder-statut_sort`

#### Upload Workflow (invitations)
- `rdvi_upload_users-invit_send-invit` - Send invitations button
- `rdvi_upload_users-invit_all-select` - Select all for invitation
- `rdvi_upload_users-invit_user-select-{id}` - Select user for invitation
- `rdvi_upload_users-invit_user-download-{id}` - Download invitation
- `rdvi_upload_users-invit_end` - Finish workflow
- `rdvi_upload_users-invit_all-folder` - All folders tab
- `rdvi_upload_users-invit_folder-error` - Error folders tab
- Status/alert elements: `*_success-alert`, `*_warning-alert`, `*_statut-tag-error-{id}`

#### Footer Links
- `rdvi_footer_help-center` - Guide link
- `rdvi_footer_stats-link` - Statistics page
- `rdvi_footer_rdvs-redirection` - RDV-Solidarites link
- `rdvi_footer_pdi-redirection` - Plateforme de l'inclusion link
- `rdvi_footer_legal-notice-link` - Legal notice
- `rdvi_footer_CGU-link` - Terms of service
- `rdvi_footer_DPA-link` - Data processing agreement
- `rdvi_footer_privacy-link` - Privacy policy
- `rdvi_footer_accessibility-link` - Accessibility statement
- `rdvi_footer_cookies-link` - Cookie settings

### Core Button Events

Standard button IDs tracked via MTM (not rdvi_ prefixed):

| ID | Description | Volume (Dec 2025) |
|----|-------------|-------------------|
| `confirm-button` | Confirmation modal confirm | 2,697 |
| `archive-button` | Archive user action | 2,392 |
| `toggle-rdv-status` | Change appointment status | 2,208 |
| `csvExportButton` | Export users to CSV | 296 |
| `btn-notification-center` | Notification center | 32 |
| `dora-link-index` | Dora service link (index) | 27 |
| `dora-link-user-loc` | Dora service link (user with location) | 19 |

### Special Events

#### Upload Progress Event
Category: `Upload`
Action: `Chargement du fichier`
Name: `Upload - resultat ok`
Description: Fired when file upload/processing completes successfully. Highest volume event (47k/month).

#### Page Configuration Views
Category: `Page Configuration`
Action: `Vues`
Name: `Page Vue Configuration`
Description: Configuration page view tracking.

### Notes

- Events use French labels (e.g., "Chargement du fichier" = "File loading")
- Page URL is used as event category, creating many unique category values per organisation/department
- Event names often include `Clic sur *******` with masked values
- The `_mtm` array is used instead of `_paq` for Matomo Tag Manager
- Tracking requires agent login and consent

## Identifiants départements (API)

**Attention :** L'API RDV-Insertion utilise des **identifiants internes**, pas les codes INSEE. Ces identifiants sont utilisés dans les URL des pages sur matomo.

Par exemple, `/departments/28/users` concerne **Loire-Atlantique (44)**, pas l'Eure-et-Loir.

### Table de correspondance

| ID | Département | Code |
|----|-------------|------|
| 1 | Ardennes | 08 |
| 2 | Drôme | 26 |
| 3 | Yonne | 89 |
| 4 | Finistère | 29 |
| 5 | Pyrénées-Atlantiques | 64 |
| 6 | Bouches-du-Rhône | 13 |
| 7 | Manche | 50 |
| 8 | Aude | 11 |
| 9 | Aveyron | 12 |
| 10 | Oise | 60 |
| 11 | Aisne | 02 |
| 12 | Meuse | 55 |
| 13 | Seine-Saint-Denis | 93 |
| 14 | Vaucluse | 84 |
| 15 | Haute-Savoie | 74 |
| 16 | Ain | 01 |
| 17 | Lozère | 48 |
| 18 | Meurthe-et-Moselle | 54 |
| 19 | Loiret | 45 |
| 20 | Puy-de-Dôme | 63 |
| 21 | Var | 83 |
| 22 | Landes | 40 |
| 23 | Haute-Garonne | 31 |
| 24 | Guadeloupe | 971 |
| 25 | Cantal | 15 |
| 26 | Creuse | 23 |
| 27 | Eure | 27 |
| 28 | Loire-Atlantique | 44 |
| 29 | Vosges | 88 |
| 30 | Rhône | 69 |
| 31 | Hauts-de-Seine | 92 |
| 32 | Bas-Rhin | 67 |
| 33 | Calvados | 14 |
| 34 | Charente-Maritime | 17 |
| 35 | Deux-Sèvres | 79 |
| 36 | Moselle | 57 |
| 37 | Paris | 75 |
| 38 | Allier - TZI | 03 |
| 39 | Lot-et-Garonne | 47 |
| 40 | Yvelines | 78 |
| 41 | Nièvre | 58 |
| 42 | Tarn | 81 |
| 43 | Alpes-Maritimes | 06 |
| 44 | Ardèche | 07 |
| 45 | Isère | 38 |
| 46 | Hérault | 34 |
| 47 | Maine-et-Loire | 49 |
| 48 | Haute-Marne | 52 |
| 49 | Nord | 59 |
| 50 | Haute-Corse | 2B |
| 51 | Vendée | 85 |
| 52 | Haut-Rhin | 68 |
| 53 | Gard | 30 |
| 54 | Pas-de-Calais | 62 |
| 55 | Gers | 32 |
| 56 | Val d'Oise | 95 |
| 57 | Val-de-Marne | 94 |
| 58 | Seine-et-Marne | 77 |
| 59 | Gironde | 33 |
| 60 | Côte d'Or | 21 |
| 61 | Loir-et-Cher | 41 |
| 62 | Marne | 51 |
| 63 | Réunion | 974 |
| 64 | Ille-et-Vilaine | 35 |
| 65 | Dordogne | 24 |
| 66 | Eure-et-Loir | 28 |
| 67 | Seine-Maritime | 76 |
| 68 | Essonne | 91 |
| 69 | Pyrénées-Orientales | 66 |
| 70 | Ariège | 09 |
| 71 | Saône-et-Loire | 71 |
| 72 | Sarthe | 72 |
| 73 | Allier - RSA | 03 |
| 74 | Haute-Loire | 43 |
| 75 | Territoire de Belfort | 90 |
| 76 | Morbihan | 56 |
| 109 | Alpes-de-Haute-Provence | 04 |
| 110 | Martinique | 972 |
| 111 | Charente | 16 |

**Note :** L'Allier a deux entrées (IDs 38 et 73) correspondant à des dispositifs différents (TZI et RSA).
