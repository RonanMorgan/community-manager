# CLAUDE.md — Contexte projet pour les agents IA

Ce fichier est la référence à jour pour tout agent (Claude ou autre) qui
travaille sur ce repo. Il documente la vision produit, ce qui a été supprimé
et pourquoi, ce qui a été gardé et pourquoi, et les décisions d'architecture
encore ouvertes. **Lisez-le avant de toucher au code.**

---

## 1. Vision du projet

Anciennement **"Marty Bot"** : un bot Mattermost piloté par des commandes en
ligne (`@marty create_projet Foo`) qui créait/synchronisait des ressources
(groupes Authentik, canaux Mattermost, collections Outline, listes Brevo,
bases NocoDB, collections Vaultwarden) en se basant uniquement sur l'état
"live" de Mattermost et Authentik — sans aucune base de données.

**Devient** : une application web — **Community Manager** — avec :

1. **Une interface de gestion de groupes**, remplaçant les commandes
   Mattermost. Un admin crée un groupe, choisit les outils à y associer
   (Mattermost et Outline par défaut, Brevo/Vaultwarden en option), et
   ajoute des utilisateurs.
2. **Une interface de visualisation**, accessible aux utilisateurs normaux
   comme aux admins, qui sert de surcouche à Authentik — dans un premier
   temps, afficher les applications OIDC disponibles pour l'utilisateur
   connecté.
3. **Une vraie base de données**, contrairement à l'ancien bot. Important
   (précision apportée après une première passe) : **Authentik et
   Mattermost restent des sources de vérité**. La base de données de
   l'appli n'est pas *la seule* source de vérité — elle vient s'ajouter à
   elles. Il faudra donc des **fonctions de synchronisation explicites**
   entre Authentik/Mattermost et la DB de l'appli (voir §4).
4. **Authentification** : connexion à l'appli via OIDC à Authentik, aussi
   bien pour les utilisateurs normaux que pour les admins.

### V0 — périmètre fonctionnel cible

- **Non-admin** : se connecter via OIDC/Authentik, voir les "Applications"
  disponibles dans Authentik (liste OIDC).
- **Admin** :
  - a accès à la même page que le non-admin ;
  - une page listant tous les groupes déjà créés, avec pour chaque groupe
    un tableau des outils concernés (Mattermost, Outline en premier lieu,
    potentiellement Brevo, Vaultwarden) ;
  - un bouton pour ajouter des utilisateurs à un groupe existant ;
  - un bouton pour créer un groupe : nom + cases à cocher pour les outils à
    y associer (Mattermost + Outline cochés par défaut).

---

## 2. État d'avancement (ce qui a été fait dans cette passe)

**Mise à jour** : la V0 de l'application web est maintenant implémentée (voir
§6 pour le détail complet — architecture technique, ce qui est fait, ce qui
reste à faire, comment lancer le tout). Le reste de cette section décrit la
première passe (nettoyage uniquement, pas encore d'appli web) — gardée telle
quelle pour l'historique.

Cette première itération a fait du **nettoyage et de la préservation**, pas
encore d'écriture de la nouvelle application web. Concrètement :

- Suppression de toute la couche "bot Mattermost piloté par commandes" :
  parsing de mentions, websocket, factory de commandes, chaque commande
  (`create_projet`, `send_email`, `update_all_user_rights`, ...), gestion des
  droits basée sur les rôles Mattermost.
- Suppression du moteur de synchronisation qui dérivait l'état des groupes
  **à partir des canaux Mattermost** (`libraries/group_sync_services.py`,
  `libraries/services/*`, `scripts/sync_mm_authentik_groups.py`). Ce moteur
  était conçu spécifiquement pour l'ancien modèle "pas de DB, Mattermost =
  unique source de vérité pour la composition des groupes". Ce modèle ne
  correspond plus à l'architecture cible — mais **son algorithme reste une
  bonne référence** pour écrire les futures fonctions de synchro DB ↔
  Mattermost/Authentik (voir §4.3).
- Suppression du `Dockerfile` / `docker-compose.yml` (pointaient sur
  `python -m app.bot`, qui n'existe plus).
- Conservation intégrale de `clients/` (tous les clients d'API), du pattern
  `config/` (chargement des variables d'env) et de `client_factory.py`.
- Réduction de la suite de tests (voir §5).
- Déplacement des scripts de maintenance indépendants du bot (nettoyage des
  comptes désactivés dans Authentik) vers `scripts/maintenance/`.
- `config/permissions_matrix.yml` déplacé vers
  `docs/legacy_reference/permissions_matrix.yml.reference` : il n'est plus
  chargé par aucun code, mais reste une bonne source d'inspiration (voir
  §4.4).

**Ce qui reste à faire** (pas commencé) : choisir la stack (backend web,
frontend, moteur de DB), concevoir le schéma de données, implémenter l'auth
OIDC, construire l'UI de gestion des groupes, et écrire les fonctions de
synchronisation Mattermost/Authentik ↔ DB.

---

## 3. Ce qui a été gardé, et pourquoi

### 3.1 `clients/` — à réutiliser tel quel

Le vrai actif du repo. Chaque client est un wrapper HTTP pur autour d'une
API externe, **sans aucune dépendance au reste du bot**. Utilisez-les
directement depuis la nouvelle application (backend) sans les réécrire.

| Client | Fichier | Points clés |
|---|---|---|
| `AuthentikClient` | `clients/authentik_client.py` | `create_group`, `get_groups_with_users` (pagination), `add_user_to_group` / `remove_user_from_group` (par PK), `get_all_users_data`, `get_all_users_pk_by_email`. API v3 Authentik (`/api/v3/core/...`). |
| `MattermostClient` | `clients/mattermost_client.py` | `create_channel`, `get_channel_by_name`, `get_users_in_channel`, `add_user_to_channel`, `get_channels_for_team`, `get_user_roles`, `list_users`/`delete_user`, plus les endpoints Focalboard (`duplicate_board`, `create_board_from_template`). Contient aussi `slugify()` (utilisée pour dériver les noms de canaux Mattermost — rapatriée ici depuis l'ancien `libraries/services/mattermost.py` supprimé). |
| `OutlineClient` | `clients/outline_client.py` | `create_group` (= créer une collection), `list_collections`, `add_user_to_collection` / `remove_user_from_collection`, `list_users`/`delete_user`. |
| `BrevoClient` | `clients/brevo_client.py` | Listes de contacts (`create_list`, `get_list_by_name`), `add_contact_to_list` / `remove_contact_from_list`, `send_transactional_email`, gestion des dossiers (`get_folder_id_by_name`). |
| `NocoDBClient` | `clients/nocodb_client.py` | Bases (`create_base`, `get_base_by_title`), utilisateurs de base (`invite_user_to_base`, `update_base_user`, `delete_base_user`). |
| `VaultwardenClient` | `clients/vaultwarden_client.py` | Le plus complexe : pilote la CLI `bw` (login/unlock/sync) **et** l'API Vaultwarden. Nécessite `BW_PASSWORD` en variable d'env et le binaire `bw` installé (voir l'ancien `Dockerfile` supprimé — `npm install -g @bitwarden/cli` sera à réintroduire dans la nouvelle image si Vaultwarden est utilisé). |

`clients/client_factory.py::create_clients()` construit un dict `{nom:
client}` à partir de `config`, en ignorant silencieusement (avec un
warning) les services dont les variables d'env ne sont pas renseignées.
Réutilisez ce pattern.

### 3.2 `config/` — pattern à faire évoluer, pas à jeter

`config/__init__.py` charge aujourd'hui de simples constantes depuis les
variables d'environnement (via `python-dotenv`). C'est volontairement
minimal et n'a **pas** été adapté à un framework web (pas de
`pydantic-settings`, pas de config par environnement, pas de gestion de
secrets). À faire une fois la stack backend choisie.

### 3.3 `scripts/maintenance/` — utilitaires indépendants, à conserver

Ces scripts ne dépendent pas de l'ancien bot : ils partent d'Authentik (déjà
traité comme source de vérité pour l'identité) et nettoient les comptes des
autres outils qui n'existent plus dans Authentik.

- `user_management.py` : `remove_inactive_users()` — supprime/désactive dans
  Outline, NocoDB, Mattermost, Vaultwarden les comptes absents d'Authentik.
- `brevo_user_sync.py` : synchronise les utilisateurs Authentik vers une
  liste Brevo, avec mapping d'attributs custom Authentik → attributs Brevo.
- `update_brevo_list_and_remove_user.py` : script d'orchestration (à lancer
  en cron) combinant les deux ci-dessus.

Ces scripts restent utiles indépendamment de la nouvelle appli web — mais à
terme, leur logique devrait probablement être ré-exposée comme tâches
planifiées de l'appli plutôt que comme scripts cron autonomes.

### 3.4 `docs/legacy_reference/permissions_matrix.yml.reference`

L'ancien fichier `config/permissions_matrix.yml`. **N'est plus chargé par
aucun code.** Gardé pour référence car il montre le mapping "type d'entité →
quels outils, avec quel pattern de nommage, avec quel niveau d'accès (lecture
seule / lecture-écriture)". C'est une bonne base de réflexion pour le modèle
de données des groupes, mais **ne pas le réimporter tel quel** : son modèle
suppose des catégories d'entités fixes (`PROJET`/`ANTENNE`/`POLES`) avec des
patterns de nommage et une distinction "standard"/"admin" par canal. Le
besoin V0 est différent : des groupes **libres** (nom choisi par l'admin),
avec une liste d'outils cochés à la création, sans notion de canal
standard/admin.

---

## 4. Ce qui a été supprimé, et pourquoi

### 4.1 Couche bot Mattermost (commandes en ligne)

`app/bot.py`, `app/websocket_handler.py`, `app/commands/*`,
`app/result_manager.py`, `app/user_right_manager.py`, `app/enums.py`.

Toute cette couche existait pour : se connecter au websocket Mattermost,
parser les mentions `@marty <commande> <args>`, router vers une commande, et
formater les résultats en messages Mattermost (avec emojis `:white_check_mark:`
etc.). Elle est intégralement remplacée par une UI web. Rien à en garder
techniquement — mais la **logique métier** de `create_resources_for_entity()`
(dans l'ex-`libraries/resource_creation.py`, supprimé) montrait la séquence
correcte d'appels multi-outils pour "créer les ressources d'une entité" :
1. Créer le groupe Authentik.
2. Créer le canal Mattermost (+ y ajouter le demandeur).
3. (optionnel) Créer un board Focalboard depuis un template.
4. Créer la collection Outline.
5. Créer la liste Brevo (avec gestion de dossier).
6. Créer la base NocoDB.
7. Créer la collection Vaultwarden.

C'est cette séquence qu'il faudra réimplémenter derrière le bouton "créer un
groupe" de la V0 (en l'adaptant : plus de distinction standard/admin, tous
les outils optionnels sauf Mattermost/Outline cochés par défaut).

### 4.2 Moteur de synchro "Mattermost = source unique de vérité"

`libraries/group_sync_services.py`, `libraries/services/*`
(`authentik.py`, `mattermost.py`, `outline.py`, `brevo.py`, `nocodb.py`,
`vaultwarden.py`, `base.py`), `scripts/sync_mm_authentik_groups.py`.

Ce code implémentait deux modes de synchro (`WITH_AUTHENTIK` et
`MM_TO_TOOLS`) qui **découvraient** les groupes en scannant les noms de
canaux Mattermost ou de groupes Authentik selon des patterns regex dérivés
de `permissions_matrix.yml`, puis poussait les memberships vers chaque
outil. Il n'y avait aucune notion de DB : l'état "actuel" était recalculé à
chaque exécution en interrogeant Mattermost/Authentik en direct.

C'est supprimé parce que le modèle change : les groupes seront désormais des
**enregistrements explicites en DB** (créés via l'UI), pas des entités
déduites de conventions de nommage. Mais **l'algorithme reste une bonne
référence** pour écrire les nouvelles fonctions de synchro DB ↔
Mattermost/Authentik demandées en §4.3 — notamment la gestion de la
pagination Authentik, la construction de `mm_users_for_services` (map
email → infos utilisateur), et la distinction "sync additive" (n'ajoute
jamais, cf. `update_all_user_rights`) vs "sync différentielle" (ajoute et
supprime, cf. `update_user_rights_and_remove`).

### 4.3 Tests obsolètes

Tests couvrant exclusivement le code ci-dessus :
`test_bot.py`, `test_group_sync_services.py`, `test_sync_script.py`,
`test_result_manager.py`, `test_user_right_manager.py`.

---

## 4-bis. Point important : Authentik et Mattermost restent sources de vérité

**Précision du produit (à ne pas oublier)** : contrairement à ce qu'une
première lecture du besoin "on va utiliser une base de données" pourrait
laisser penser, la DB de l'appli **ne remplace pas** Authentik/Mattermost
comme source de vérité — elle **s'ajoute** à elles.

Concrètement, cela implique :

- **Authentik reste la source de vérité pour l'identité** (comptes
  utilisateurs, emails, attributs) et — au moins pour l'instant — pour les
  **groupes** (un "groupe" au sens Authentik existe indépendamment de la
  DB de l'appli).
- **Mattermost reste la source de vérité pour les canaux et leurs membres.**
- **La DB de l'appli** stocke a minima : la liste des groupes créés via
  l'UI, avec pour chacun quels outils y sont associés (Mattermost ? Outline ?
  Brevo ? Vaultwarden ?) — c'est une information qui n'existe dans aucun des
  outils externes (Authentik ne sait pas qu'un de ses groupes est "aussi"
  lié à une collection Outline précise). La DB est donc le point central qui
  fait le lien entre entités externes (groupe Authentik #X, canal
  Mattermost #Y, collection Outline #Z) pour un même "groupe logique" côté
  appli.
- Il faudra des **fonctions de synchronisation explicites**, dans les deux
  sens selon les cas :
  - **DB → outils** : quand un admin crée un groupe ou ajoute un
    utilisateur via l'UI, l'appli doit répercuter l'action vers Authentik
    (créer le groupe / ajouter l'utilisateur) et vers chaque outil coché.
  - **Outils → DB** : Authentik/Mattermost peuvent aussi évoluer en dehors
    de l'appli (admin qui modifie un groupe directement dans Authentik, un
    utilisateur qui rejoint un canal Mattermost manuellement). Il faut donc
    un job de synchro périodique (ou déclenché) qui réconcilie l'état de la
    DB avec l'état réel d'Authentik/Mattermost, pour que la page de
    visualisation (§1, point 2) reste fidèle à la réalité.
- Ce point n'est **pas encore implémenté**. À concevoir : fréquence de
  synchro (cron ? webhook Authentik/Mattermost si disponible ? à la
  demande ?), gestion des conflits (qui gagne si la DB et Authentik
  divergent ?), et quelles entités sont *dérivées* d'Authentik/Mattermost
  (lecture seule côté DB, juste mises en cache) vs *possédées* par la DB de
  l'appli (l'association groupe ↔ outils, qui n'existe nulle part ailleurs).
- Voir §4.2 ci-dessus : l'ancien moteur de synchro Mattermost-vers-outils,
  bien que supprimé, reste la meilleure référence de code existante pour
  cette logique (gestion de la pagination Authentik, construction des maps
  email → utilisateur, distinction sync additive/différentielle).

---

## 5. Tests

La suite de tests initiale (~220 tests sur les clients) était surdimensionnée
— beaucoup de variantes redondantes du même cas d'erreur. Elle a été réduite
à ~117 tests couvrant, pour chaque méthode de chaque client : le cas
nominal, un cas d'erreur représentatif (HTTP error, en général), et les cas
limites qui reflètent une vraie logique métier (pagination, gestion de
session/token pour Vaultwarden, etc.). Le fichier `test_outline_client_2.py`
(doublons purs de `test_outline_client.py`) a été supprimé entièrement.

```bash
PYTHONPATH=. pytest tests/ scripts/maintenance/
# 117 passed
```

Si vous ajoutez de nouvelles méthodes aux clients, gardez cette discipline :
un test nominal + un test d'erreur représentatif suffisent dans la majorité
des cas, sauf logique de contrôle réellement complexe (cf. Vaultwarden).

---

## 6. V0 de l'application web — ce qui a été implémenté

### 6.1 Stack technique (décisions prises)

- **Backend** : Python / **FastAPI**, synchrone, pour réutiliser `clients/`
  tel quel (aucun des clients n'est async).
- **Frontend** : **pas de framework JS séparé**. Pages rendues côté serveur
  avec Jinja2 (`backend/templates/`) + un peu de JS vanilla
  (`backend/static/app.js`) pour l'interactivité (édition inline, modales,
  appels `fetch` vers l'API JSON). Choix fait pour garder le
  `docker-compose` à un seul conteneur applicatif (pas de build frontend
  séparé, pas de conteneur nginx supplémentaire).
- **Base de données** : **PostgreSQL** en production/docker-compose, SQLite
  supporté aussi (utilisé par les tests, et utilisable en dev local sans
  Docker) — géré via `DATABASE_URL` (SQLAlchemy détecte le dialecte depuis
  l'URL).
- **ORM** : SQLAlchemy 2.x (style `Mapped[...]`).
- **Auth** : **Authlib** pour le flow OIDC contre Authentik.
- **Tables créées via `Base.metadata.create_all()`** au démarrage (pas de
  migration Alembic pour cette V0 — voir limite connue en §6.5).

### 6.2 Ce qui est implémenté

- **Page `/applications`** : liste les applications Authentik en direct via
  `AuthentikClient.list_applications()` (nouvelle méthode ajoutée au
  client). Aucune donnée stockée en DB pour cette page.
- **Page `/groups`** : tableau groupes × outils. Une seule colonne
  fonctionnelle en V0 : **Outline**. Chaque cellule affiche le nom éditable
  de la ressource (`GroupResource.display_name`) ; éditer et sortir du
  champ déclenche `PATCH /api/group-resources/{id}` qui renomme la vraie
  collection Outline (`OutlineClient.update_collection_name()`, nouvelle
  méthode ajoutée) puis met à jour la DB.
- **Bouton "Créer un groupe"** → modale avec nom + cases à cocher par outil
  (seule "Outline" est cochée/activable en V0 ; les autres sont visibles
  mais désactivées avec la mention "bientôt disponible", pour que l'UI
  n'ait pas à être retouchée quand un outil est ajouté). `POST /api/groups`
  crée le `Group`, une `GroupResource` par outil coché, et **provisionne
  réellement la collection Outline** via `OutlineClient.create_group()`. Si
  Outline échoue ou n'est pas configuré, la ressource est créée avec
  `status=error` plutôt que de faire échouer toute la requête — l'admin
  voit l'erreur dans le tableau (badge rouge) plutôt qu'un groupe qui
  disparaît silencieusement.
- **Clic sur une ressource "active"** → modale listant les utilisateurs
  **réels de la collection Outline correspondante**, récupérés en direct à
  chaque ouverture (`GET /api/group-resources/{id}/users`, jamais depuis la
  DB) avec leur droit (`read` / `read_write`), grâce à la nouvelle méthode
  `OutlineClient.get_collection_memberships_with_permission()` (les
  méthodes existantes ne remontaient pas le champ `permission`).
- **Ajout d'utilisateur dans la modale** (`POST .../users`) : droit
  `read` par défaut, modifiable dans un `<select>` avant envoi. Si l'email
  ne correspond à aucun utilisateur Outline (pas encore provisionné via
  OIDC), l'API renvoie une **erreur 422 explicite** ("aucun utilisateur
  Outline trouvé pour l'email ... doit s'être connecté au moins une fois")
  plutôt qu'un échec silencieux — décision produit actée.
- **Retrait d'utilisateur** (`DELETE .../users/{id}`) : ajouté en
  complément naturel de l'ajout (pas explicitement demandé mais
  symétrique et déjà supporté par `OutlineClient.remove_user_from_collection`).
- **`audit_logs`** : chaque action admin (création de groupe, provisioning
  de ressource — succès ou échec —, renommage, ajout/retrait d'utilisateur)
  écrit une ligne (`backend/routers/api.py::_log()`). Pas encore de page
  pour la consulter (à faire si utile).
- **Authentification OIDC togglable** : `AUTH_ENABLED=false` (défaut) →
  toute requête est traitée comme un admin factice
  (`config.DEV_FAKE_ADMIN_EMAIL`), aucun appel à Authentik. `AUTH_ENABLED=true`
  → vrai flow OIDC (Authlib) contre Authentik ; l'admin est déterminé par
  l'appartenance au groupe Authentik `config.ADMIN_GROUP_NAME` (lu depuis le
  claim `groups` renvoyé par l'userinfo/ID token — **à vérifier/adapter
  selon la config réelle du scope OIDC dans Authentik**, voir §6.5).

### 6.3 Fichiers ajoutés

```
backend/
  main.py                 Entrée FastAPI (lifespan, montage routers/static)
  database.py              Engine SQLAlchemy + session (get_db)
  models.py                 Group, GroupResource, AuditLog (voir §3-bis pour le schéma)
  schemas.py                 Schémas Pydantic (requêtes/réponses API)
  auth.py                     OIDC via Authlib + toggle AUTH_ENABLED
  outline_service.py          Service layer entre les routes et OutlineClient
                               (contient PROVISIONERS : registre tool -> fonction
                               de création, pour ajouter un outil sans toucher aux routes)
  routers/
    pages.py                    GET /, /applications, /groups (HTML)
    auth_routes.py               /login, /auth/callback, /logout
    api.py                        API JSON (CRUD groupes/ressources/utilisateurs)
  templates/                base.html, applications.html, groups.html (Jinja2)
  static/                   style.css, app.js (vanilla JS, pas de build step)
  tests/                    conftest.py + 4 fichiers de tests (17 tests)

Dockerfile                 Image du backend (python:3.12-slim + uvicorn)
docker-compose.yml         Services `db` (postgres:16-alpine) + `backend`
```

Modifications aux fichiers existants :
- `clients/outline_client.py` : + `get_collection_memberships_with_permission()`,
  + `update_collection_name()`
- `clients/authentik_client.py` : + `list_applications()`
- `config/__init__.py` : + variables DB/auth/OIDC (voir `.env.example`)
- `requirements.txt` : + fastapi, uvicorn, sqlalchemy, psycopg2-binary,
  jinja2, python-multipart, authlib, itsdangerous, httpx, email-validator

### 6.4 Comment lancer l'application

**Avec Docker (recommandé)** :
```bash
cp .env.example .env
# éditer .env : au minimum OUTLINE_URL / OUTLINE_TOKEN pour que "Créer un
# groupe" provisionne réellement une collection. AUTH_ENABLED=false par
# défaut (pas besoin de configurer OIDC pour tester en local).
docker compose up --build
# -> http://localhost:8000/groups
```

**Sans Docker (dev)** :
```bash
cp .env.example .env
# laisser DATABASE_URL=sqlite:///./community_manager.db (valeur par défaut)
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

**Tests** :
```bash
PYTHONPATH=. pytest tests/ scripts/maintenance/ backend/tests/
# 145 passed
```

### 6.5 Limites connues / à traiter ensuite

- **Migrations** : les tables sont créées par `Base.metadata.create_all()`
  au démarrage, pas de vraie migration (Alembic). Suffisant pour une V0 sur
  base vide ; à corriger avant toute évolution de schéma sur une base qui
  contient déjà des données.
- **OIDC — claim `groups`** : le code suppose que le token/userinfo
  Authentik renvoie un claim `groups` listant les groupes de l'utilisateur.
  C'est le comportement par défaut d'Authentik **si le scope `groups` (ou
  équivalent) est activé sur le Provider OIDC** — à vérifier/configurer
  côté Authentik lors de la mise en place réelle, sinon `require_admin`
  refusera tout le monde. Pas testé contre une vraie instance Authentik
  dans cette passe (pas d'accès à une instance depuis l'environnement de
  développement) — **à valider en priorité en conditions réelles**.
- **Synchro DB ↔ Mattermost/Authentik** (§4-bis) : toujours pas implémentée.
  La V0 ne fait que Outline, en écriture directe (DB → Outline) au moment
  de l'action admin. Aucun job de réconciliation périodique.
- **Autres outils (Mattermost, Brevo, Vaultwarden)** : le schéma et l'UI
  sont prêts (`ToolName` enum, checkboxes désactivées, colonne de tableau
  facile à ajouter), mais aucun provisioner n'est branché. Pour en ajouter
  un : écrire l'équivalent de `outline_service.py` pour l'outil, l'ajouter
  au dict `PROVISIONERS`, et ajouter le tool à `functional_tools` /
  `table_tools` dans `backend/routers/pages.py`.
- **Page non-admin** : pas implémentée (V0 = pages admin uniquement, comme
  demandé). `require_admin` renvoie 403 à tout utilisateur authentifié non
  admin.
- **`docker-compose.yml` non testé avec un vrai daemon Docker** dans cet
  environnement (pas de Docker disponible côté agent). Le serveur a en
  revanche été testé réellement avec `uvicorn` (la même commande que le
  `CMD` du Dockerfile) contre les dépendances exactes de `requirements.txt`
  installées dans un venv vierge — donc l'appli elle-même est validée, mais
  **le premier `docker compose up --build` reste à faire par vous**.
- **`class Config` Pydantic dépréciée** : déjà migré vers `ConfigDict` dans
  `backend/schemas.py`. Pas de dette technique connue à ce sujet.



## 6-bis. V0.1 — corrections page Applications + synchronisation Authentik → DB

Suite aux premiers tests en conditions réelles (vraies clés API Authentik /
Outline / Mattermost), deux ajustements :

### 6-bis.1 Page Applications : icônes + sections

- **Bug icônes corrigé** : le template utilisait `app.meta_icon`, qui peut
  être un **chemin relatif** vers un fichier uploadé dans Authentik (ex.
  `/media/application-icons/foo.png`), inutilisable tel quel hors du
  contexte d'Authentik. La page utilise maintenant `app.meta_icon_url`
  (URL absolue fournie par l'API Authentik) en priorité, avec repli sur
  `meta_icon` préfixé par `AUTHENTIK_URL` si besoin
  (`backend/routers/pages.py::_resolve_icon_url()`). Un `onerror` côté HTML
  bascule sur un badge-lettre si l'image ne charge toujours pas.
- **Sections ajoutées** : Authentik permet de définir un champ `group`
  (texte libre) sur chaque Application, utilisé par Authentik lui-même pour
  regrouper les apps sur sa page "Library". La page `/applications` fait
  maintenant de même : elle groupe par ce champ
  (`backend/routers/pages.py::_group_applications_by_section()`), sections
  triées alphabétiquement, les apps sans groupe atterrissant dans une
  section "Autres" en fin de page.

### 6-bis.2 Synchronisation Authentik → DB (bouton "Synchroniser")

Nouveau bouton sur la page `/groups`, `POST /api/sync`
(`backend/routers/api.py::sync_from_authentik`). Comportement, tel que
spécifié :

1. Récupère tous les groupes Authentik (`AuthentikClient.get_groups_with_users()`).
2. Pour chaque groupe Authentik : crée (ou retrouve, si déjà lié) le
   `Group` correspondant côté DB. Le lien se fait via le nouveau champ
   `Group.authentik_group_id` (le `pk` Authentik) — s'il n'existe pas
   encore mais qu'un groupe du même **nom** existe déjà en DB (créé
   manuellement avant la synchro), on le lie plutôt que d'en recréer un.
3. Pour Outline et Mattermost (voir `_SYNC_FINDERS` dans `api.py`) :
   cherche une ressource du **même nom exact** que le groupe Authentik.
   - Trouvée → `GroupResource.status = ACTIVE`, `external_id` et
     `display_name` renseignés à partir de la vraie ressource. Affichée
     avec un **point vert** dans le tableau.
   - Pas trouvée → `GroupResource.status = NOT_FOUND` (nouveau statut),
     affichée avec un point gris et "Aucune correspondance".
   - Erreur API → `GroupResource.status = ERROR`, remontée dans la réponse
     (`errors: [...]`) et affichée à l'écran.
4. **Aucune écriture dans Outline/Mattermost** : ce endpoint est
   volontairement en lecture seule côté outils (découverte uniquement).
   Rien n'est créé/modifié chez eux.
5. Idempotent : relancer la synchro ne duplique pas les groupes déjà liés
   (testé, voir `backend/tests/test_sync.py::test_sync_is_idempotent_on_group_name`).

Détails d'implémentation notables :
- **Mattermost** : les canaux sont adressés par leur *slug* (nom
  URL-safe), pas leur nom d'affichage. Le matching applique donc
  `slugify(nom_du_groupe_authentik)` avant d'appeler
  `MattermostClient.get_channel_by_name()`. Voir `backend/mattermost_service.py`.
- **Nouvelle méthode client** `MattermostClient.get_channel_members_with_roles()`
  (ajoutée dans cette passe) : combine `GET /channels/{id}/members` (rôles)
  et `get_users_in_channel()` (détails utilisateur), sur le même principe
  que ce qui avait été fait pour Outline. Permet à la modale "utilisateurs"
  de fonctionner aussi pour une ressource Mattermost trouvée par la synchro
  (lecture seule : **pas d'ajout/retrait d'utilisateur Mattermost depuis
  l'UI pour l'instant**, seulement Outline — cf. §6-bis.4).
- **Nouvelle méthode client** `OutlineClient` réutilisée :
  `find_collection_by_name()` (ajoutée dans `backend/outline_service.py`,
  s'appuie sur `list_collections(name=...)` qui fait déjà un matching par
  nom exact côté client existant).
- **Filtrage des groupes Authentik** : aucun filtre appliqué — **tous**
  les groupes Authentik sont synchronisés, y compris les groupes internes
  d'Authentik (ex. `authentik Admins`). Pas demandé explicitement dans
  cette passe ; à affiner si besoin (ex. exclure par préfixe/attribut).

### 6-bis.3 Modèle de données : ce qui a changé

- `Group.authentik_group_id` (string, nullable, unique) : le `pk` du
  groupe Authentik correspondant, quand connu.
- `ResourceStatus.NOT_FOUND` : nouveau statut ("synchronisé depuis
  Authentik, mais aucune ressource du même nom trouvée dans l'outil").
- Table `group_resources` : le tableau affiche maintenant aussi la colonne
  **Mattermost** (`table_tools = ["outline", "mattermost"]`), en plus
  d'Outline. Le bouton "Créer un groupe" ne coche/active en revanche
  toujours qu'Outline (`functional_tools`), car la création manuelle d'un
  canal Mattermost depuis l'UI n'est pas encore câblée — seule la
  *découverte* via `/api/sync` l'est.

### 6-bis.4 Ce qui reste explicitement pour plus tard (confirmé avec l'utilisateur)

- Boutons de **création/suppression de groupe** au sens "provisionner
  réellement une nouvelle ressource" pour Mattermost (Outline fonctionne
  déjà, voir §6.2).
- **Ajout/retrait d'utilisateur** sur une ressource Mattermost depuis
  l'UI (aujourd'hui lecture seule ; le client a pourtant déjà
  `add_user_to_channel()`, il manque juste le branchement + un
  `remove_user_from_channel()` côté client à écrire).
- Filtrage des groupes Authentik à exclure de la synchro (groupes
  internes, etc.).

## 6-ter. V0.2 — correction de la régression Postgres (migrations Alembic) + erreur Authentik explicite

Suite à ton premier vrai test en production (`docker compose up`), deux
régressions détectées :

### 6-ter.1 "Internal Server Error" sur /groups — cause et correctif

**Cause racine** : jusqu'ici, le schéma de la base était géré uniquement par
`Base.metadata.create_all()` au démarrage (voir l'ancienne limite §6.5,
maintenant corrigée). Cette fonction SQLAlchemy **crée les tables qui
n'existent pas encore, mais ne modifie jamais une table déjà existante**.
Ta base Postgres avait déjà une table `groups` (créée lors du déploiement
précédent, avant l'ajout de `authentik_group_id` dans la passe
"synchronisation Authentik"). Au redémarrage du conteneur avec le nouveau
code, la colonne manquait toujours en base → chaque requête sur `/groups`
plantait avec `UndefinedColumn: groups.authentik_group_id does not exist`.

Reproduit à l'identique en local contre un vrai Postgres (pas SQLite) avant
correction, pour confirmer le diagnostic.

**Correctif : de vraies migrations, avec Alembic.**
- Nouveau dossier `migrations/` (Alembic), configuré pour lire
  `DATABASE_URL` depuis `config` (donc depuis les mêmes variables d'env que
  l'appli, pas une config séparée).
- Une migration initiale (`migrations/versions/..._initial_schema.py`),
  générée par autogénération contre un vrai Postgres et testée (upgrade
  vérifié, `alembic check` confirme zéro divergence avec les modèles).
- **`docker-entrypoint.sh`** (nouveau) : exécute `alembic upgrade head`
  avant de lancer `uvicorn`. Le `Dockerfile` l'utilise comme `ENTRYPOINT`.
  Donc `docker compose up` applique désormais toujours les migrations en
  attente avant de démarrer — ce type de régression ne peut plus se
  reproduire silencieusement.
- **Colonnes enum passées en VARCHAR** (`native_enum=False` sur
  `GroupResource.tool` et `.status`) plutôt qu'en type ENUM natif Postgres.
  Un ENUM natif nécessite `ALTER TYPE ... ADD VALUE` pour chaque nouvelle
  valeur (pénible avec Alembic, interdit dans une transaction sur les
  anciennes versions de Postgres) — sachant que de nouvelles valeurs
  viendront forcément (nouveaux outils, nouveaux statuts), une colonne
  VARCHAR classique évite ce piège pour toutes les migrations futures.
- **`backend/main.py`** : `create_all()` n'est plus utilisé qu'en SQLite
  (dev local rapide / tests, base jetable). Sur Postgres, le schéma est
  **exclusivement** géré par Alembic — l'appli ne touche plus au schéma
  elle-même au démarrage.
- **CI** : nouveau job `migrations` dans `.github/workflows/tests.yml`, qui
  fait tourner un vrai service Postgres, applique les migrations, puis lance
  `alembic check` — la build échoue si un modèle change sans migration
  associée (vérifié : j'ai simulé une divergence pour confirmer que le job
  la détecte bien, exit code non-zéro).

**Pour débloquer ton déploiement actuel** (aucune donnée à perdre, la table
`groups` était vide) :
```bash
docker compose down -v   # supprime le volume Postgres, repart de zéro
docker compose up --build
```
Le nouveau `docker-entrypoint.sh` appliquera la migration initiale
automatiquement au démarrage.

**Pour toute future évolution du modèle** (`backend/models.py`), le
réflexe devient :
```bash
DATABASE_URL=postgresql+psycopg2://... alembic revision --autogenerate -m "description"
# relire la migration générée avant de la committer (autogénération imparfaite)
alembic upgrade head   # pour tester en local
```

### 6-ter.2 "Aucune application trouvée" — cause et correctif UX

Tes logs montraient `403 - Token invalid/expired` côté Authentik : un vrai
souci de token (expiré/révoqué côté Authentik), pas un bug applicatif — à
régénérer côté Authentik puis vérifier sa prise en compte dans le `.env`
du conteneur.

Cela dit, ça a révélé un vrai bug UX : `AuthentikClient.list_applications()`
avalait toute erreur HTTP et renvoyait `[]` (liste vide) — indiscernable
d'un "il n'y a vraiment aucune application". La page affichait donc
silencieusement "Aucune application trouvée" au lieu du vrai problème.

**Correctif** : `list_applications()` renvoie maintenant `None` sur erreur
(au lieu de `[]`), et `backend/routers/pages.py` affiche un message
explicite dans ce cas ("Impossible de récupérer les applications... token
invalide ou expiré — voir les logs du serveur").

### 6-ter.3 Tests ajoutés

- `tests/test_authentik_client.py` : succès + erreur HTTP de
  `list_applications()` (vérifie qu'elle renvoie bien `None`, pas `[]`).
- `backend/tests/test_applications_page.py` : la page affiche le message
  d'erreur explicite (et jamais "Aucune application trouvée") quand
  l'appel Authentik échoue.
- 145 tests au total désormais.





## 7. Décisions ouvertes (non tranchées, à décider avec l'utilisateur)

Ne pas trancher unilatéralement ces points sans validation :

1. ~~Stack backend~~ **Tranché** : FastAPI, voir §6.1.
2. ~~Stack frontend~~ **Tranché pour la V0** : Jinja2 + JS vanilla, voir
   §6.1. Une vraie SPA (React/Vue) reste possible plus tard si le besoin
   d'interactivité grandit, mais n'était pas nécessaire pour ce périmètre.
3. ~~Moteur de base de données~~ **Tranché** : PostgreSQL (docker-compose),
   SQLite supporté pour les tests/dev.
4. ~~Bibliothèque OIDC~~ **Tranché** : Authlib. Non testé contre une
   vraie instance Authentik — voir limite en §6.5.
5. **Définition du rôle "admin"** : tranché en principe (groupe Authentik
   dédié, `ADMIN_GROUP_NAME`, lu depuis le claim `groups`) mais **pas
   validé en conditions réelles** — voir §6.5.
6. **Fréquence/déclenchement des synchros DB ↔ Mattermost/Authentik**
   (cf. §4-bis) : **partiellement tranché** — la synchro Authentik → DB
   existe maintenant en déclenchement manuel (bouton "Synchroniser", voir
   §6-bis.2), en lecture seule côté outils. Toujours pas de job périodique
   automatique, et toujours pas de synchro DB → outils au-delà de la
   création/renommage manuel déjà en place pour Outline.
7. **Page non-admin** (visualisation seule pour un utilisateur normal) :
   pas implémentée, à spécifier si toujours souhaitée après cette V0 admin.
8. **Consultation des `audit_logs`** : les logs sont écrits mais il n'y a
   pas encore de page pour les consulter. À faire si utile.
9. **Filtrage des groupes Authentik synchronisés** : `/api/sync` importe
   actuellement TOUS les groupes Authentik sans exception (voir §6-bis.2).
   À valider si des groupes doivent être exclus (groupes internes
   Authentik, groupes techniques, etc.).
10. **Ajout/retrait d'utilisateur Mattermost depuis l'UI** : pas encore
    câblé (lecture seule pour l'instant), voir §6-bis.4.
11. ~~Gestion du schéma de base de données~~ **Tranché** : Alembic, voir
    §6-ter.1. Les migrations doivent désormais être écrites/relues à chaque
    changement de `backend/models.py` — ce n'est plus automatique.
