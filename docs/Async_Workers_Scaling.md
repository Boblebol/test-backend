# Async, workers Celery et scaling futur

Date : 2026-06-19
Statut : note d'evolution

## Decision courte

La cible n'est pas "plus de workers partout".

La bonne cible est :

```text
plus de concurrence quand on attend le reseau
+ debit externe controle globalement
+ Postgres protege
```

Autrement dit :

- Celery reste le moteur des traitements longs ;
- `gevent` peut aider pour les tasks I/O-bound ;
- Redis peut porter des quotas distribues ;
- Postgres doit garder des sessions courtes et peu de connexions ;
- les lectures confort peuvent aller plus tard sur read replica.

## Concurrence vs debit

Il faut separer deux notions.

La concurrence, c'est le nombre de tasks capables d'attendre en meme temps.

Le debit, c'est le nombre d'appels reels autorises vers un service externe.

Exemple :

```text
200 tasks OCR en attente
mais seulement 20 appels OCR/min autorises
```

Ajouter des workers augmente la capacite a attendre. Cela ne doit pas multiplier
les appels externes.

## Pourquoi `gevent` peut servir

Un worker Celery `prefork` est robuste et simple. C'est le bon choix par defaut.

`gevent` devient interessant si une task fait surtout :

```text
appel reseau externe
attente
petit parsing
ecriture DB courte
```

Dans ce cas, beaucoup de tasks attendent le reseau. `gevent` permet d'en garder
plus en attente avec moins de process.

Mais `gevent` n'accelere pas le calcul. Il augmente la concurrence. Sans
garde-fous, il peut saturer les partenaires, Redis ou Postgres.

## Rate limit distribue

Un quota local par worker ne suffit pas.

Si chaque worker autorise `100 appels/min` et qu'on lance 3 workers, le debit
reel devient `300 appels/min`.

Le modele preferable est un bucket partage dans Redis :

```text
ocr_provider_global = 600 appels/min
metadata_provider_global = 300 appels/min
partner_global = 120 appels/min
```

Tous les workers consomment les memes tokens. On peut ajouter des workers sans
augmenter automatiquement le debit externe.

## Granularite des quotas

Commencer simple :

- quota par type de service externe ;
- un cout simple : `1 task = 1 token`.

Puis affiner seulement si les mesures le demandent :

- quota par endpoint ;
- quota par organisation ;
- poids selon nombre de pages ;
- poids selon taille estimee du prompt ou du document.

Trop de buckets rendent le systeme difficile a comprendre et a regler.

## Protection de Postgres

Le risque principal avec plus de concurrence est de garder trop de connexions DB.

Deux regles :

1. borner le pool SQLAlchemy ;
2. ne pas garder une session DB ouverte pendant un appel externe.

Exemple de config prudente pour workers :

```text
DB_POOL_SIZE=1 ou 2
DB_MAX_OVERFLOW=0
DB_POOL_TIMEOUT=5
DB_POOL_RECYCLE=1800
```

Le nombre total de connexions doit rester calculable :

```text
api_instances * pool_api
+ admin_instances * pool_admin
+ worker_instances * pool_worker
+ marge scripts/monitoring
```

Avec autoscaling, cette formule devient critique. Un worker qui peut ouvrir 10
connexions devient dangereux si on en lance 20.

## Sessions DB courtes

Le bon pattern dans une task :

```text
ouvrir DB
marquer step running
commit + fermer
appel externe long
ouvrir DB
stocker resultat + mark success
commit + fermer
```

La base sert a lire et ecrire l'etat. Elle ne doit pas payer l'attente reseau.

## Read replicas

Si les lectures augmentent, on peut decharger le primaire avec une read replica.

Restent sur le primaire :

- creation document ;
- `complete-upload` ;
- transitions de steps ;
- webhook partenaire ;
- relances admin ;
- recovery jobs ;
- lecture juste apres une mutation.

Peuvent aller sur replica :

- listes documents ;
- details hors action immediate ;
- dashboards admin ;
- Metabase ;
- exports ;
- monitoring non critique.

La contrepartie est claire : une replica peut avoir quelques secondes de retard.
C'est acceptable pour une liste ou un dashboard, pas pour decider une transition
metier.

## Redis et RabbitMQ

Redis est un choix pragmatique pour ce test :

- simple en Docker ;
- deja utilise pour Pub/Sub SSE ;
- suffisant pour une demo lisible ;
- maitrise dans le temps disponible.

Pour une production tres orientee queues, RabbitMQ serait a evaluer :

- dead-letter queues ;
- meilleure lecture native des files ;
- backpressure ;
- routage et acknowledgements plus riches ;
- outils d'administration dedies.

Le code metier ne doit pas dependre directement du broker. Celery garde cette
decision relativement interchangeable.

## Workers par type

Ne pas tout mettre dans un seul type de worker.

| Worker | Usage |
| --- | --- |
| `prefork` | defaut, robuste, tasks DB-heavy ou generales |
| `gevent` | appels reseau nombreux, tasks I/O-bound |

En local, Docker Compose separe deja les queues pour rendre Flower lisible :

| Service local | Queue |
| --- | --- |
| `worker-pipeline` | `documents.pipeline` |
| `worker-ocr` | `documents.ocr` |
| `worker-metadata` | `documents.metadata` |
| `worker-chunking` | `documents.chunking` |
| `worker-external-call` | `documents.external_call` |
| `worker-recovery` | `documents.recovery` |

Cette separation locale sert surtout a l'observabilite. En production, il faudra
ajouter les vraies limites : concurrence, DB, quotas et monitoring.

## Autoscaling

L'autoscaling doit regarder plus que la profondeur de queue.

Signaux utiles :

- nombre de tasks en queue ;
- age de la plus vieille task ;
- tokens disponibles dans le bucket Redis ;
- taux de remplissage du bucket ;
- connexions et CPU Postgres ;
- CPU/memoire workers ;
- nombre de workers deja actifs.

Regle simple :

```text
queue vide longtemps      -> 0 worker
Postgres en mauvaise sante -> ne pas augmenter
tokens faibles             -> ne pas augmenter fort
queue grossit + tokens OK  -> augmenter progressivement
```

L'augmentation doit etre prudente, pas lineaire.

Exemple :

```text
10 tasks      -> 1 worker
100 tasks     -> 2 workers
1 000 tasks   -> 4 workers
10 000 tasks  -> 8 workers
```

Cela evite de lancer 50 workers qui attendent des tokens ou saturent Postgres.

## Prefetch

Pour garder une repartition lisible :

```text
worker_prefetch_multiplier = 1
```

Un worker ne doit pas reserver trop de tasks a l'avance. Sinon une queue peut
sembler vide alors que des tasks sont bloquees dans un worker.

## Observabilite necessaire

Avant de regler finement les quotas, il faut mesurer :

- profondeur des queues ;
- age de la plus vieille task ;
- duree des tasks ;
- retries et echecs ;
- tasks refusees par rate limit ;
- tokens disponibles ;
- temps d'attente de tokens ;
- connexions Postgres ;
- pool timeouts ;
- latence Redis.

Sans ces mesures, les quotas deviennent des suppositions.

## Strategie de mise en place

Ordre raisonnable :

1. Sessions DB courtes.
2. Pools DB bornes.
3. `worker_prefetch_multiplier = 1`.
4. Queues separees visibles dans Flower.
5. Buckets Redis simples par service externe.
6. Worker `gevent` seulement pour les queues I/O-bound.
7. Presets de quotas par environnement.
8. Monitoring puis ajustement.

## Conclusion

Le point essentiel :

```text
Gevent augmente la capacite a attendre.
Redis limite le debit reel.
Postgres doit etre protege par design.
```

Si ces trois sujets restent separes, le systeme peut scaler sans devenir
imprevisible.
