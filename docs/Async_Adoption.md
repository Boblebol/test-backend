# Faut-il passer tout le projet en async ?

Date : 2026-06-19
Statut : decision d'architecture

## Decision courte

Non. Je ne passerais pas tout le projet en `async def` maintenant.

Le projet est deja asynchrone la ou ca compte pour l'utilisateur :

- FastAPI repond vite ;
- Celery execute les traitements longs hors requete HTTP ;
- PostgreSQL reste la source de verite ;
- Redis transporte les jobs et les evenements ;
- le client suit l'avancement via SSE.

Le point important : "async" ne veut pas dire "mettre `async def` partout".
Ici, le systeme est non bloquant cote produit parce que les traitements lents ne
tournent pas dans le worker HTTP.

## Pourquoi rester simple

Pour la cible actuelle du sujet, environ `1 000 documents/jour` et `50`
utilisateurs concurrents, une migration async complete apporterait peu de valeur
immediate.

Elle ajouterait surtout de la complexite :

- repositories SQLAlchemy sync a migrer ;
- sessions et transactions a repenser ;
- tests DB a adapter ;
- risque d'appeler du code bloquant depuis un endpoint `async def` ;
- risque d'augmenter la concurrence sans proteger Postgres ni les partenaires.

Un endpoint `async def` qui appelle du code sync bloquant peut etre pire qu'un
endpoint sync classique. Il bloque l'event loop et rend la latence moins
previsible.

## Ce qui peut rester sync

Ces parties peuvent rester sync sans probleme pour ce rendu :

- repositories ;
- services metier internes ;
- transactions PostgreSQL ;
- Flask admin ;
- seed et scripts de bootstrap ;
- endpoints CRUD simples.

Le code sync est plus lisible, plus facile a tester, et suffisant tant que les
traitements longs passent par Celery.

## Ou l'async pourra servir plus tard

L'async devient utile quand le temps principal est de l'attente reseau.

Exemples :

- appel OCR externe ;
- appel LLM ou metadata externe ;
- API partenaire lente ;
- beaucoup de connexions SSE ;
- enrichissements via APIs tierces.

La trajectoire raisonnable est progressive :

1. Garder FastAPI et SQLAlchemy sync tant que les mesures ne disent pas le contraire.
2. Garder Celery comme mecanisme principal de traitement asynchrone.
3. Introduire des clients HTTP async si les appels externes deviennent nombreux.
4. Evaluer des workers Celery `gevent` pour les queues I/O-bound.
5. Migrer SQLAlchemy async seulement si la DB sync devient un vrai goulot mesure.

## Garde-fous avant plus de concurrence

Avant d'augmenter fortement la concurrence, il faut avoir :

- pools DB bornes ;
- sessions DB courtes ;
- rate limits globaux pour les services externes ;
- observabilite sur queues, retries et erreurs ;
- strategie d'autoscaling prudente.

Sans ces garde-fous, l'async peut juste envoyer plus vite le systeme dans les
quotas externes ou la limite de connexions Postgres.

## Signaux qui changeraient la decision

Je reconsidererais si on observe :

- queues Celery qui grossissent alors que CPU faible ;
- workers surtout en attente reseau ;
- beaucoup de connexions SSE simultanees ;
- cout infra eleve pour des workers qui attendent ;
- besoin mesure de lancer beaucoup d'appels externes en parallele.

Si le goulot est Postgres ou le CPU, l'async ne sera probablement pas la premiere
solution.

## Conclusion

Pour ce test, le bon choix est de rester simple :

- sync pour l'API et la DB ;
- Celery pour les traitements longs ;
- async cible plus tard, seulement la ou les mesures le justifient.
