# Recovery jobs

Cette note explique le job de rattrapage autour du pipeline.

## Probleme couvert

Le flux normal de `POST /documents/{id}/complete-upload` fait deux actions :

1. passer le document en `uploaded` en base ;
2. envoyer le pipeline dans Celery.

Si Redis ou Celery tombe juste apres le commit DB, le document peut rester en
`uploaded` sans pipeline lance.

Le client ne peut pas simplement rappeler `complete-upload`, car le document
n'est plus en `waiting_upload`.

## Job actuel

Task Celery :

```text
app.modules.processing.recovery.task.recover_uploaded.recover_stale_uploaded_documents_task
```

Comportement :

- lance par Celery Beat toutes les heures ;
- cherche les documents `uploaded` depuis plus de 24h ;
- limite a 100 documents par execution ;
- relance le pipeline complet.

Dans le code, `app/celery_app.py` declare le `beat_schedule`
`recover-stale-uploaded-documents`. Docker Compose lance aussi un service
`beat`, et `worker-recovery` consomme la queue `documents.recovery`.

Le job ne touche pas aux documents `processing`, `waiting_partner`, `ready` ou
`failed`. Il corrige uniquement le trou "DB commit OK, enqueue Celery KO".

## Pourquoi c'est suffisant ici

Pour un test local, c'est un filet de securite simple :

- facile a comprendre ;
- testable ;
- limite a un statut precis ;
- sans nouvelle infrastructure.

Ce n'est pas une garantie transactionnelle stricte.

## Evolution production

En production stricte, le vrai modele serait une outbox transactionnelle :

Une outbox transactionnelle est une table en base qui sert de boite d'envoi
fiable. Au lieu de modifier la base puis d'appeler Celery dans une deuxieme
operation fragile, on ecrit la modification metier et l'evenement a publier dans
la meme transaction PostgreSQL.

Si le commit reussit, l'evenement est durable. Si le commit echoue, rien n'est
publie. Un worker separe lit ensuite l'outbox et publie vers Celery jusqu'a
reussite.

1. la mutation DB ecrit aussi un evenement durable ;
2. un worker publie l'evenement vers Celery ;
3. l'evenement est marque traite seulement apres publication reussie.

Le recovery actuel reste utile comme protection operationnelle, mais il ne
remplace pas l'outbox.

## Ajouter un autre recovery

Si un autre cas apparait, il faut creer une task dediee, pas elargir celle-ci.

Exemples :

- document `processing` avec step `running` trop ancienne ;
- document `waiting_partner` depuis plusieurs jours ;
- nettoyage de jobs externes expires ;
- relance controlee d'une strategie de pipeline.

Pattern :

1. selection repository tres ciblee ;
2. fonction `*_in_session` testable sans worker ;
3. wrapper Celery ;
4. queue dediee ;
5. planification Beat si besoin ;
6. seuils et statuts documentes.
