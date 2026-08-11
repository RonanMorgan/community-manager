# Community Manager

Application de gestion de la communauté : synchronisation entre **Authentik**
(identité) et **Mattermost** (collaboration), et gestion de groupes donnant
accès à un ensemble d'outils (Mattermost, Outline, Brevo, NocoDB,
Vaultwarden).

> **Voir [CLAUDE.md](./CLAUDE.md) pour le contexte complet** : vision produit,
> data model, décisions d'architecture, ce qui est fait et ce qui reste à
> faire. Ce README ne donne qu'un démarrage rapide.

## Synchronisation Authentik → DB

Authentik est la source de vérité pour les groupes. Sur la page `/groups`,
le bouton **« Synchroniser depuis Authentik »** :
1. crée (ou relie, si déjà connu) un groupe côté appli pour chaque groupe Authentik ;
2. cherche, pour Outline et Mattermost, une ressource du même nom exact ;
3. affiche un point vert si trouvée (avec accès à la liste réelle des
   membres et leurs droits), un point gris sinon.

Aucune écriture n'est faite dans Outline/Mattermost par cette synchronisation
— c'est une découverte en lecture seule. Voir CLAUDE.md §6-bis pour le détail.

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
# 145 passed
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
