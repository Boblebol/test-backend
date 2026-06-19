# Flask admin interne

Le test technique ne demande pas d'UI interne. Le projet livre quand meme un
Flask admin local pour rendre la review et la demo plus simples.

## Role

Le Flask admin sert a inspecter et agir localement.

Il ne remplace pas l'API publique FastAPI. Il ne s'adresse pas aux utilisateurs
d'organisation. Il represente une surface interne Primmo.

En local :

```bash
make bootstrap
make links
```

URL : <http://127.0.0.1:8001>

## Point fort

L'admin ne reimplemente pas le metier.

Les vues lisent via `AdminQueries`. Les actions reutilisent les services
applicatifs existants :

- creation document ;
- ecriture MinIO ;
- completion upload ;
- enqueue Celery ;
- webhook partenaire ;
- relances pipeline.

Cela garde une seule logique metier. L'admin est une surface d'operation, pas un
deuxieme backend.

## Vues principales

| Vue | Role |
| --- | --- |
| `/test-cockpit` | parcours court pour reviewer le pipeline complet |
| `/` | dashboard snapshot |
| `/documents` | liste filtreable et actions bulk |
| `/documents/new` | upload ou generation locale de lots |
| `/documents/<id>` | detail document et steps |
| `/documents/<id>/actions` | actions webhook et relances |
| `/processing-steps` | lecture globale des steps courantes |
| `/organizations` | tenants et volumes |
| `/users` | utilisateurs et volumes |

## Test cockpit

`/test-cockpit` est le point d'entree le plus utile pour une review.

Il permet de :

1. choisir un user seed ;
2. creer des faux PDFs ;
3. lancer les pipelines ;
4. suivre les documents jusqu'a `waiting_partner` ;
5. simuler un webhook partenaire `completed` ou `rejected` ;
6. verifier le passage en `ready` ou `failed`.

La page auto-refresh toutes les 10 secondes. Elle evite d'aller chercher les
documents a la main dans la base ou dans Swagger.

## Dashboard snapshot

La home lit PostgreSQL et montre l'etat courant :

- total organisations, users et documents ;
- documents par statut ;
- steps par statut ;
- derniers documents ;
- derniers echecs ;
- documents en attente du webhook partenaire.

Ce n'est pas du temps reel. Le bouton refresh relit simplement la base.

## Documents

La liste documents sert au triage :

- filtrer par organisation, user, statut ou recherche texte ;
- ouvrir le detail ;
- ouvrir les actions d'un document ;
- appliquer des actions bulk ;
- creer des documents en masse.

`/documents/new` permet deux usages locaux :

- uploader plusieurs PDFs pour un user ;
- generer de faux documents pour tester les workers et l'admin.

Le preset local `50 users / 200 documents` simule une tranche de charge sans
lancer directement les `~1 000` documents journaliers du sujet.

## Actions webhook

L'admin peut simuler le partenaire :

- `Validate document` produit un webhook `status=completed` ;
- `Invalidate document` produit un webhook `status=rejected` ;
- le body JSON et la signature `X-Partner-Signature` sont affiches.

Ces actions reutilisent le meme secret HMAC et les memes services de processing.
Elles sont marquees comme actions de test.

## Detail document

La page `/documents/<id>` montre le document et son groupe courant de steps :

- statut document ;
- fichier ;
- `storage_key` ;
- owner ;
- `external_job_id` ;
- erreur courante ;
- OCR, metadata, chunking, external_call, partner_webhook ;
- statut, tentatives, `updated_by`, `result_json`, erreur.

Elle auto-refresh toutes les 6 secondes. Elle sert a comprendre rapidement ou un
document est bloque.

## Relances pipeline

Les relances admin utilisent les strategies de
`app/modules/processing/pipeline/strategies.py`.

| Action | Strategie | Effet |
| --- | --- | --- |
| Relancer tout | `all` | reset complet puis pipeline complet |
| Relancer OCR | `ocr` | OCR puis dependances aval |
| Relancer apres OCR | `post_ocr` | metadata + chunking puis external call |
| Relancer metadata | `metadata` | metadata puis external call |
| Relancer chunking | `chunking` | chunking puis external call |
| Relancer external call | `external_call` | nouvel appel partenaire |

Avant chaque relance, l'admin remet l'etat durable en coherence :

- document en `processing` ;
- steps dependantes en `pending` ;
- resultats aval invalides supprimes ;
- ancien `external_job_id` supprime si necessaire.

Les relances partielles verifient leurs prerequis. Si un resultat amont manque,
l'action est `skipped` et aucune task Celery n'est enqueuee.

## Metabase reste separe

Le Flask admin doit rester centre sur les actions controlees.

Pour les tableaux, filtres, stats et explorations metier, Metabase est plus
adapte. Cela evite de transformer l'admin maison en outil BI fragile.

## Securite

Le service admin actuel est local.

Pour une vraie surface interne, il faudrait ajouter :

- login/logout interne ;
- secret de session ;
- hash de mot de passe admin ;
- CSRF sur les POST ;
- cookies `HttpOnly`, `SameSite`, `Secure` hors local ;
- restriction reseau ;
- audit durable des actions ;
- pas d'exposition de secrets.

## Evolutions utiles

Ordre logique :

1. Auth admin.
2. Table `internal_action_logs`.
3. Audit autour des relances et webhooks.
4. Tests unitaires plus fins sur les actions admin.
