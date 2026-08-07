# Community Manager

Application de gestion de la communauté : synchronisation entre **Authentik**
(identité) et **Mattermost** (collaboration), et gestion de groupes donnant
accès à un ensemble d'outils (Mattermost, Outline, Brevo, NocoDB,
Vaultwarden).

> **Ce repo est en cours de refonte.** L'ancienne version était un bot
> Mattermost piloté par des commandes en ligne (`@marty create_projet ...`).
> Cette approche est abandonnée au profit d'une application web avec base de
> données. Voir **[CLAUDE.md](./CLAUDE.md)** pour le contexte complet, les
> décisions d'architecture et l'état d'avancement — c'est la référence à jour,
> ce README ne décrit que la base de code telle qu'elle existe aujourd'hui.

## Ce qui existe aujourd'hui

Le repo, à ce stade, ne contient **pas encore d'application web**. Il
contient la partie qui a été explicitement conservée de l'ancien bot : les
clients d'API vers chaque outil, plus quelques scripts de maintenance
indépendants. C'est la base sur laquelle la nouvelle application sera
construite.

```
clients/                 Clients API purs vers chaque outil (aucune dépendance
                          au bot). C'est le cœur réutilisable du projet.
  authentik_client.py       Groupes, utilisateurs (lecture/écriture)
  mattermost_client.py      Canaux, membres, rôles, boards (Focalboard)
  outline_client.py         Collections, membres
  brevo_client.py           Listes de contacts, emails transactionnels
  nocodb_client.py          Bases, utilisateurs de base
  vaultwarden_client.py     Collections (via CLI `bw` + API)
  client_factory.py         Construit les clients configurés depuis `config`

config/
  __init__.py               Chargement des variables d'environnement

scripts/maintenance/     Scripts autonomes, indépendants de l'ancien bot :
                          nettoient les comptes des outils qui n'existent
                          plus dans Authentik (Authentik = source de vérité).
  user_management.py
  brevo_user_sync.py
  update_brevo_list_and_remove_user.py

docs/legacy_reference/   Documentation de l'ancien système, gardée comme
                          référence (pas du code actif).
  permissions_matrix.yml.reference

tests/                   Tests des clients (suite réduite aux cas les plus
                          importants — voir CLAUDE.md).
```

## Configuration

```bash
cp .env.example .env
# renseigner les valeurs
pip install -r requirements.txt
pip install -r requirements-dev.txt   # pour les tests / lint
```

## Tests

```bash
PYTHONPATH=. pytest tests/ scripts/maintenance/
```

## Prochaines étapes

Voir **[CLAUDE.md](./CLAUDE.md)**.
