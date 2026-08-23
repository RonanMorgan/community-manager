# Community Manager

Application de gestion de la communauté : synchronisation entre **Authentik**
(identité) et **Mattermost** (collaboration), et gestion de groupes donnant
accès à un ensemble d'outils (Mattermost, Outline, Brevo, NocoDB,
Vaultwarden).

> **Voir [CLAUDE.md](./CLAUDE.md) pour le contexte complet** : vision produit,
> data model, décisions d'architecture, ce qui est fait et ce qui reste à
> faire. Ce README ne donne qu'un démarrage rapide.

## Catégories et gabarits de nom configurables

Quels outils un groupe obtient, sous quel nom, et si un canal admin lui est
associé, est piloté par **`config/resource_templates.yml`** — pas par du
code. C'est ce fichier qui définit par exemple que les Projets ont un canal
Mattermost admin dédié (`"{base_name} Admin"`) alors que les Pôles et
Antennes n'en ont pas. Modifier un gabarit de nom, ajouter/retirer un canal
pour une catégorie, ou changer les préfixes de détection (`Projet`, `Pôle`,
`Antenne`) se fait en éditant ce fichier, sans toucher au code. Voir
CLAUDE.md §6-octies.

## Création de groupe

Le bouton **« Créer un groupe »** sur la page `/groups` crée systématiquement
le groupe correspondant dans **Authentik** (obligatoire, non désactivable —
c'est la source de vérité), et optionnellement une collection **Outline**
et/ou un canal **Mattermost** (cochés par défaut, décochables). Pour un nom
commençant par « Projet », un canal Mattermost admin dédié (avec son propre
groupe Authentik) est créé automatiquement si Mattermost est coché — ce
n'est pas une case à part, c'est obligatoire pour cette catégorie. Si la
création Authentik échoue, rien n'est créé côté application.

## Synchronisation Authentik → DB

Authentik est la source de vérité pour les groupes. Sur la page `/groups`,
le bouton **« Synchroniser depuis Authentik »** :
1. crée (ou relie, si déjà connu) un groupe côté appli pour chaque groupe
   Authentik, et **supprime ceux qui n'existent plus dans Authentik**
   (sauf les groupes créés manuellement, jamais touchés par cette
   réconciliation) ;
2. classe automatiquement chaque groupe en **Projet / Pôle / Antenne**
   selon le préfixe de son nom (les groupes non reconnus atterrissent dans
   une section « Non catégorisés », avec assignation manuelle possible) ;
3. pour un Projet, rattache le canal Mattermost admin dédié (groupe
   Authentik « ... Admin ») à son projet parent plutôt que d'en faire un
   groupe séparé ;
4. cherche, pour Outline et Mattermost, une ressource du même nom exact ;
5. affiche un point vert si trouvée (avec accès à la liste réelle des
   membres et leurs droits), un point gris sinon — avec un bouton 🔗
   pour associer manuellement une ressource si le nom a divergé entre
   Authentik et l'outil (recherche par mots-clés).

Aucune écriture n'est faite dans Outline/Mattermost par cette synchronisation
— c'est une découverte en lecture seule. Voir CLAUDE.md §6-bis et
§6-quinquies pour le détail.

## Démarrage rapide

**Avec Docker (recommandé)** :

```bash
cp .env.example .env
# éditer .env : au minimum OUTLINE_URL / OUTLINE_TOKEN pour que la création
# de groupe provisionne réellement une collection Outline.
# AUTH_ENABLED=false par défaut : pas besoin de configurer OIDC pour tester
# en local (toute requête est traitée comme un admin).
docker compose up --build
# -> http://localhost:8000/groups
```

Les migrations de base de données (Alembic) sont appliquées automatiquement
au démarrage du conteneur `backend`, avant que le serveur ne démarre — voir
`docker-entrypoint.sh`. Si vous mettez à jour un déploiement existant et
tombez sur une erreur de colonne manquante, c'est probablement que le
schéma a changé sans migration disponible avant cette version : voir
CLAUDE.md §6-ter.1 pour le contexte, et en dernier recours
`docker compose down -v` repart d'un schéma propre (⚠️ supprime les
données existantes).

**Sans Docker (dev)** :

```bash
cp .env.example .env   # laisser DATABASE_URL=sqlite:///./community_manager.db
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Avec SQLite (valeur par défaut), le schéma est créé automatiquement au
démarrage, pas besoin de lancer les migrations à la main. Si vous utilisez
Postgres hors Docker, lancez `alembic upgrade head` avant de démarrer le
serveur.

**Tests** :

```bash
PYTHONPATH=. pytest tests/ scripts/maintenance/ backend/tests/
# 201 passed
```

## Structure du repo

```
backend/                 Application web (FastAPI + Jinja2 + JS vanilla)
  main.py                   Entrée de l'app
  models.py                  Group, GroupResource, AuditLog
  routers/                    pages.py (HTML), api.py (JSON), auth_routes.py (OIDC)
  templates/, static/         Front (pas de build step)
  tests/                       Tests du backend

migrations/               Migrations Alembic (schéma de la base)
clients/                 Clients API purs vers chaque outil (Authentik,
                          Mattermost, Outline, Brevo, NocoDB, Vaultwarden)
config/                  Chargement des variables d'environnement
scripts/maintenance/     Scripts de nettoyage Authentik-driven, indépendants
docs/legacy_reference/   Documentation de l'ancien système, gardée comme référence
tests/                   Tests des clients

Dockerfile, docker-compose.yml, docker-entrypoint.sh   Déploiement (Postgres + backend)
```

## Prochaines étapes

Voir la section 7 de **[CLAUDE.md](./CLAUDE.md)** ("Décisions ouvertes").
