# Pagination et filtres publics

Etat : implemente sur `GET /documents`.

Cette note explique le contrat public de liste documents.

Objectif : une liste tenant-safe, stable quand la table grossit, et compatible
avec une future read replica.

## Contrat

```http
GET /documents?limit=50&status=ready&cursor=<opaque_cursor>
Authorization: Bearer <jwt>
```

Parametres :

| Parametre | Role |
| --- | --- |
| `limit` | nombre d'elements, borne de `1` a `100`, defaut `50` |
| `cursor` | curseur opaque retourne par la page precedente |
| `status` | filtre optionnel sur le statut document |
| `owner_user_id` | filtre optionnel sur le proprietaire |
| `created_from` | borne basse inclusive sur `created_at` |
| `created_to` | borne haute inclusive sur `created_at` |

Reponse :

```json
{
  "items": [],
  "next_cursor": null
}
```

`next_cursor=null` signifie qu'il n'y a pas de page suivante. Le curseur est
opaque : le client le renvoie tel quel.

## Pourquoi un curseur

La liste est ordonnee par `(created_at DESC, id DESC)`.

Ce choix evite les problemes de `OFFSET` :

- le cout ne grandit pas avec la profondeur de page ;
- une insertion recente ne decale pas les pages deja parcourues ;
- `id` stabilise l'ordre si deux documents ont le meme `created_at` ;
- le filtre tenant reste simple : `org_id = current_user.org_id`.

L'API demande `limit + 1` lignes. La ligne supplementaire sert seulement a savoir
s'il faut retourner un `next_cursor`.

## Filtres et index

Regles importantes :

- `org_id` vient du JWT, jamais du client ;
- les filtres sont conjunctifs ;
- le curseur doit etre utilise avec les memes filtres que la premiere page.

Index deja utiles :

- `ix_documents_org_created_id` pour la liste par tenant ;
- `ix_documents_org_status` pour tenant + statut ;
- index simples sur `org_id`, `owner_user_id` et `status`.

Je n'ajoute pas d'index composes a l'aveugle. Ils ont un cout d'ecriture. On les
ajoute seulement si les mesures montrent une requete chaude.

## Front demo

Le front `:8080` utilise ce contrat :

- premiere page avec `limit=50` ;
- filtres de statut cote API ;
- bouton `Charger plus` base sur `next_cursor`.

La demo teste donc le vrai contrat public, pas une pagination en memoire.

## Read replica

`GET /documents` est un bon candidat pour une future read replica : une liste
peut accepter quelques secondes de retard.

Restent sur le primaire :

- mutations documents ;
- `complete-upload` ;
- webhook partenaire ;
- relances admin ;
- recovery jobs ;
- lecture juste apres une mutation utilisateur.

La trajectoire est detaillee dans
[`Technical_Strategy.md`](Technical_Strategy.md) et
[`Async_Workers_Scaling.md`](Async_Workers_Scaling.md).

## Limites

Hors scope actuel :

- tri public configurable ;
- recherche texte ;
- filtres metier plus riches ;
- routage primary/replica effectif en local ;
- sauvegarde de vues ou filtres admin.

Le contrat de base est deja la : liste paginee, filtree, tenant-safe.
