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

## 6. Décisions ouvertes (non tranchées, à décider avec l'utilisateur)

Ne pas trancher unilatéralement ces points sans validation :

1. **Stack backend** (framework web + langage). Le code conservé est en
   Python (clients synchrones `requests`) — un backend Python (FastAPI,
   Django...) permettrait de réutiliser `clients/` tel quel ; un autre choix
   de langage impliquerait de réécrire les clients.
2. **Stack frontend** et niveau d'intégration (SSR, SPA...).
3. **Moteur de base de données** et schéma (voir §4-bis pour les
   contraintes fonctionnelles à respecter).
4. **Bibliothèque OIDC** côté appli pour le login via Authentik.
5. **Définition du rôle "admin"** côté nouvelle appli : l'ancien bot
   définissait l'admin par le rôle `system_admin` de Mattermost
   (`user_right_manager.is_admin`, supprimé). Ce critère n'a plus de sens
   une fois que le login se fait via OIDC/Authentik — il faudra probablement
   définir l'admin par appartenance à un groupe Authentik dédié, exposé via
   les claims OIDC. À valider.
6. **Fréquence/déclenchement des synchros DB ↔ Mattermost/Authentik**
   (cf. §4-bis).
