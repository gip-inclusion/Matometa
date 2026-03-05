# Support Emplois de l'Inclusion

Données du support utilisateurs des Emplois de l'Inclusion, issues de **Zendesk**.

**Schéma :** `public` sur Metabase STATS (`database_id = 2`)
**Mise à jour :** En temps réel via webhooks n8n à chaque création ou modification de ticket
**Source :** Zendesk

## Schéma relationnel

```
support_emplois_tickets_infos  ──┐
                                  ├── id_du_ticket ──> support_emplois_tickets_metrics
support_emplois_tickets_tags   ──┘                     (1 ligne par ticket)
(N lignes par ticket)
```

Les trois tables se joignent via `id_du_ticket` (integer).

## Tables

### public.support_emplois_tickets_metrics

Métriques clés par ticket : délais de traitement, nombre de réouvertures, etc.

**Volumétrie :** 1 ligne par ticket

| Colonne | Type | Description |
|---------|------|-------------|
| `id_du_ticket` | integer | Clé primaire (FK vers les deux autres tables) |
| `created_at` | date | Date de création du ticket |
| `assigned_at` | date | Date d'assignation à un agent |
| `solved_at` | date | Date de résolution |
| `reopens_number` | integer | Nombre de réouvertures du ticket |
| `replies_number` | integer | Nombre de réponses échangées |
| `first_reply_time_minutes` | integer | Délai avant la première réponse (en minutes) |
| `first_resolution_time_minutes` | integer | Délai avant la première résolution (en minutes) |
| `full_resolution_time_minutes` | integer | Délai total jusqu'à la résolution définitive (en minutes) |

```sql
-- Temps de réponse moyen par mois (en heures)
SELECT
    DATE_TRUNC('month', created_at) as mois,
    COUNT(*) as nb_tickets,
    ROUND(AVG(first_reply_time_minutes) / 60.0, 1) as delai_premiere_reponse_h,
    ROUND(AVG(full_resolution_time_minutes) / 60.0, 1) as delai_resolution_h
FROM public.support_emplois_tickets_metrics
WHERE solved_at IS NOT NULL
GROUP BY 1
ORDER BY 1;
```

---

### public.support_emplois_tickets_tags

Tags associés aux tickets. Une ligne par tag par ticket.

**Volumétrie :** N lignes par ticket (autant que de tags)

| Colonne | Type | Description |
|---------|------|-------------|
| `tag_id` | text | Clé primaire composite (`{id_du_ticket}_{tag}`) |
| `id_du_ticket` | integer | FK vers les deux autres tables |
| `tag` | text | Valeur du tag |

**Origine des tags :**
- **Automatique** : générés depuis le formulaire de contact rempli par l'utilisateur
- **Manuel** : ajoutés par les agents de support

**Format des tags :** Les tags encodent souvent des informations structurées, ex :
- `c.b_aide-inscription_num-ss-invalide` → type d'acteur (`c.b`), sujet (`aide-inscription`), sous-problème (`num-ss-invalide`)
- `ddets`, `ddets-dreets` → type d'institution concernée
- `closed_by_merge` → action effectuée sur le ticket

```sql
-- Tags les plus fréquents
SELECT tag, COUNT(*) as nb_tickets
FROM public.support_emplois_tickets_tags
GROUP BY tag
ORDER BY nb_tickets DESC
LIMIT 20;

-- Tickets avec un tag spécifique
SELECT t.*, i.sujet_du_ticket, m.full_resolution_time_minutes
FROM public.support_emplois_tickets_tags t
JOIN public.support_emplois_tickets_infos i ON t.id_du_ticket = i.id_du_ticket
JOIN public.support_emplois_tickets_metrics m ON t.id_du_ticket = m.id_du_ticket
WHERE t.tag = 'ddets'
ORDER BY i.ticket_cree_date DESC;
```

---

### public.support_emplois_tickets_infos

Informations contextuelles sur chaque ticket : identité du demandeur, sujet, canal.

**Volumétrie :** 1 ligne par ticket

| Colonne | Type | Description |
|---------|------|-------------|
| `id_du_ticket` | integer | Clé primaire (FK vers les deux autres tables) |
| `e_mail_du_demandeur` | text | Email de la personne au nom de qui le ticket est créé |
| `e_mail_de_l_envoyeur` | text | Email de la personne qui a effectivement soumis le ticket (peut différer si soumis par un tiers) |
| `sujet_du_ticket` | text | Intitulé du ticket |
| `ticket_cree_date` | date | Date de création (format date) |
| `ticket_cree_horodatage` | timestamp | Date et heure de création (format timestamp) |
| `canal` | text | Canal de contact (ex: `Web`) |

**Note :** `e_mail_du_demandeur` et `e_mail_de_l_envoyeur` peuvent différer si un agent ou un tiers soumet le ticket au nom d'un utilisateur.

```sql
-- Vue complète d'un ticket
SELECT
    i.id_du_ticket,
    i.ticket_cree_date,
    i.sujet_du_ticket,
    i.canal,
    i.e_mail_du_demandeur,
    m.first_reply_time_minutes,
    m.full_resolution_time_minutes,
    m.reopens_number,
    STRING_AGG(t.tag, ', ' ORDER BY t.tag) as tags
FROM public.support_emplois_tickets_infos i
JOIN public.support_emplois_tickets_metrics m ON i.id_du_ticket = m.id_du_ticket
LEFT JOIN public.support_emplois_tickets_tags t ON i.id_du_ticket = t.id_du_ticket
GROUP BY i.id_du_ticket, i.ticket_cree_date, i.sujet_du_ticket, i.canal,
         i.e_mail_du_demandeur, m.first_reply_time_minutes,
         m.full_resolution_time_minutes, m.reopens_number
ORDER BY i.ticket_cree_date DESC;
```

## Cas d'usage typiques

### Volume de tickets dans le temps

```sql
SELECT
    DATE_TRUNC('month', ticket_cree_date) as mois,
    COUNT(*) as nb_tickets,
    COUNT(DISTINCT e_mail_du_demandeur) as demandeurs_uniques
FROM public.support_emplois_tickets_infos
GROUP BY 1
ORDER BY 1;
```

### Tickets non résolus

```sql
SELECT i.id_du_ticket, i.sujet_du_ticket, i.ticket_cree_date,
       m.reopens_number, m.replies_number
FROM public.support_emplois_tickets_infos i
JOIN public.support_emplois_tickets_metrics m ON i.id_du_ticket = m.id_du_ticket
WHERE m.solved_at IS NULL
ORDER BY i.ticket_cree_date;
```

### Lien avec les utilisateurs Emplois

L'email du demandeur peut être croisé avec `public.utilisateurs` pour identifier le type d'utilisateur (prescripteur, employeur, etc.) :

```sql
SELECT
    u.type as type_utilisateur,
    COUNT(DISTINCT i.id_du_ticket) as nb_tickets,
    ROUND(AVG(m.full_resolution_time_minutes) / 60.0, 1) as delai_resolution_h
FROM public.support_emplois_tickets_infos i
LEFT JOIN public.utilisateurs u ON i.e_mail_du_demandeur = u.email
JOIN public.support_emplois_tickets_metrics m ON i.id_du_ticket = m.id_du_ticket
GROUP BY u.type
ORDER BY nb_tickets DESC;
```
