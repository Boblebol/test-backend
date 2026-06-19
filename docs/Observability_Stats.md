# Observabilite, Metabase et dashboards

Date : 2026-06-19
Statut : note d'architecture

## Decision courte

Metabase sert a lire le present.

Le modele actuel garde l'etat courant des documents et des steps. Il ne garde
pas encore l'historique complet des executions.

Donc les dashboards actuels doivent repondre a des questions simples :

- quels documents sont bloques maintenant ;
- quelles steps sont en erreur maintenant ;
- quelles organisations utilisent la plateforme maintenant ;
- quels resultats sont manquants maintenant.

Ils ne doivent pas pretendre calculer des tendances historiques fiables.

## Separation des outils

Chaque outil a un role clair :

| Outil | Role |
| --- | --- |
| FastAPI | API publique et Swagger |
| Flask admin | actions operationnelles locales |
| Flower | runtime Celery : workers, queues, retries |
| Metabase | lecture metier de PostgreSQL |

Le Flask admin ne doit pas devenir un outil BI. Il doit rester centre sur les
actions controlees : inspecter, relancer, simuler un webhook.

Metabase couvre mieux les besoins de lecture : filtres, tableaux, dashboards,
questions ad hoc.

## Ce que la base permet aujourd'hui

Le modele courant permet de lire vite l'etat d'un document :

```text
documents
document_processing_steps
document_extracted_data
```

Chaque document a un petit groupe fixe de steps courantes. C'est le meme choix
que dans [`Technical_Strategy.md`](Technical_Strategy.md) : lecture stable,
bornee, `O(1)` par document.

Ce modele sait repondre a :

- combien de documents sont `processing`, `waiting_partner`, `ready`, `failed` ;
- quelle step bloque un document ;
- quelle est la derniere erreur connue ;
- combien de tentatives sont visibles sur la step courante ;
- quel user ou tenant porte les documents ;
- quels resultats extraits existent maintenant.

Ce modele ne sait pas repondre proprement a :

- combien de temps a dure chaque tentative ;
- quel etait le p95 hier ou cette semaine ;
- comment les erreurs evoluent dans le temps ;
- quelle version de provider a produit quel resultat ;
- combien de retries historiques ont eu lieu avant le dernier etat.

Pour ces questions, il faut une couche append-only.

## Dashboards actuels

`scripts/bootstrap_metabase.py` cree quatre dashboards locaux.

### Operations snapshot

Objectif : lire l'etat courant de la plateforme.

Cartes utiles :

- documents par statut ;
- documents actifs par step courante ;
- matrice step/statut ;
- tentatives visibles par step ;
- documents en attente partenaire par age du dernier update.

Ce dashboard dit : "voici l'etat maintenant".

### Documents problematiques

Objectif : trouver quoi investiguer en premier.

Cartes utiles :

- documents `failed` ;
- echecs par step ;
- documents actifs anciens ;
- documents `waiting_partner` anciens ;
- incoherences de snapshot.

Exemples d'incoherences :

- `waiting_partner` sans `external_job_id` ;
- `ready` sans `partner_result_json` ;
- step `success` sans resultat attendu.

### Usage

Objectif : lire l'usage courant par tenant et user.

Cartes utiles :

- documents par organisation ;
- documents par organisation et statut ;
- documents par user ;
- echecs par organisation ;
- attente partenaire par organisation.

Ce n'est pas encore une analyse d'adoption dans le temps. C'est une photo du
contenu actuel de la base.

### Qualite des donnees extraites

Objectif : verifier que le pipeline produit une donnee utile, pas seulement des
statuts techniques.

Cartes utiles :

- documents `ready` sans texte OCR ;
- documents `ready` sans metadata ;
- documents `ready` sans chunks ;
- repartition des types de documents ;
- couverture du resultat partenaire.

## Ce qu'il ne faut pas afficher comme fiable

Avec le modele actuel, il faut eviter :

- p50/p95 de duree pipeline ;
- duree moyenne OCR, metadata, chunking, external call ;
- taux d'echec par jour/semaine ;
- evolution des retries dans le temps ;
- comparaison provider A/B ;
- cout moyen par document ;
- adoption hebdomadaire.

Ces chiffres peuvent etre interessants. Mais les deduire du snapshot courant
donnerait des resultats fragiles.

Formulation a garder :

```text
Aujourd'hui, Metabase montre le present.
Demain, avec une couche append-only, il pourra montrer le passe.
```

## Evolution future : historique append-only

La prochaine evolution serait d'ajouter des tables d'historique.

Modele possible :

```text
document_pipeline_runs
document_step_runs
document_result_versions
```

Ces tables ne remplacent pas les tables courantes. Elles les completent.

| Table | Role |
| --- | --- |
| `document_pipeline_runs` | une execution complete du pipeline |
| `document_step_runs` | une tentative ou execution de step |
| `document_result_versions` | une version de resultat produit |

Avec cette couche, Metabase pourrait calculer :

- p50/p95 total pipeline ;
- p50/p95 par step ;
- temps d'attente partenaire ;
- success rate par jour ;
- failure rate par step ;
- retries dans le temps ;
- qualite par version de provider ;
- adoption par organisation dans le temps.

## Event log analytique

Si les besoins analytics grossissent, on peut ajouter un event log append-only.

Exemples :

- `document.created` ;
- `document.upload.completed` ;
- `pipeline.started` ;
- `processing.step.succeeded` ;
- `processing.step.retrying` ;
- `processing.step.failed` ;
- `partner.webhook.received` ;
- `document.ready` ;
- `admin.action.triggered`.

Ordre conseille :

1. garder les tables courantes pour le produit ;
2. ajouter `pipeline_runs`, `step_runs`, `result_versions` ;
3. ajouter un event log Postgres simple si necessaire ;
4. exporter vers une base analytique seulement si les volumes le justifient.

ClickHouse serait un bon candidat pour cette derniere etape. Il est adapte aux
events append-only, aux gros volumes, aux aggregations temporelles et aux
requetes analytics : p95, taux d'erreur par periode, adoption par tenant,
comparaison provider/version.

L'idee ne serait pas de remplacer PostgreSQL. PostgreSQL resterait la base
transactionnelle du produit. ClickHouse stockerait les evenements analytiques
pour les dashboards et les explorations lourdes.

## Production

En local, Metabase lit directement PostgreSQL.

En production, il faudrait le brancher sur :

- une read replica ;
- ou une base analytique comme ClickHouse ;
- ou un export dedie.

Le primaire doit rester concentre sur les mutations : uploads, transitions de
steps, workers, webhooks, relances admin.

## Conclusion

Le choix pour ce test est volontairement simple :

- Metabase montre le snapshot courant ;
- Flask admin garde les actions ;
- Flower observe Celery ;
- l'historique complet reste une evolution future.
