# Marty Bot

Marty Bot est un assistant pour automatiser la gestion des ressources sur plusieurs services : Mattermost, Authentik, Outline, Brevo, NocoDB et Vaultwarden.

## Architecture du projet

Le projet est structuré en plusieurs répertoires clés :

-   `app/` : Contient la logique principale du bot, y compris la gestion des connexions (websocket) et le traitement des commandes.
    -   `app/commands/` : Chaque fichier définit une commande spécifique que le bot peut exécuter.
    -   `app/tests/` : Les tests unitaires du projet.
-   `clients/` : Contient les clients API pour interagir avec les services externes (Mattermost, Authentik, etc.). Chaque client est responsable de la communication avec un service spécifique.
-   `config/` : Fichiers de configuration.
    -   `.env.example` : Modèle pour le fichier `.env` qui contient les secrets et les variables d'environnement.
    -   `permissions_matrix.yml` : Fichier de configuration central qui définit les ressources à créer pour chaque type d'entité (projet, antenne, pôle).
-   `libraries/` : Contient la logique métier partagée, comme la création de ressources et la synchronisation des utilisateurs. C'est ici que la logique principale des commandes est implémentée.
-   `scripts/` : Scripts autonomes pour des tâches de maintenance ou de synchronisation.

## Configuration

### 1. Variables d'environnement

La configuration de Marty Bot est gérée via des variables d'environnement.

1.  Copiez le fichier d'exemple :
    ```bash
    cp .env.example .env
    ```
2.  Modifiez le fichier `.env` et fournissez les valeurs pour votre instance. Les variables requises sont listées dans `.env.example`.

### 2. Matrice des permissions

Le fichier `config/permissions_matrix.yml` est au cœur de la logique de création de ressources. Il permet de définir de manière déclarative les ressources à créer pour chaque type d'entité (que nous appelons `PROJET`, `ANTENNE`, `POLES`).

Pour chaque entité, vous pouvez configurer :
-   Les groupes Authentik (standard et admin).
-   Les canaux Mattermost (standard et admin), y compris leur type (public/privé).
-   Les collections Outline.
-   Les listes de contacts Brevo et le dossier de rangement.
-   Les bases de données NoCoDB.
-   Les collections Vaultwarden.

Cette approche permet d'adapter le comportement du bot sans modifier le code.

### 3. Dépendances

Assurez-vous d'avoir Python 3.8+ installé. Ensuite, installez les dépendances :

```bash
pip install -r requirements.txt
```

Pour le développement, installez aussi les dépendances de développement :

```bash
pip install -r requirements-dev.txt
```

## Commandes du bot

Pour interagir avec le bot, mentionnez-le dans un canal Mattermost suivi de la commande. Exemple : `@marty help`.

### Création de ressources

Ces commandes s'appuient sur la `permissions_matrix.yml` pour créer un ensemble de ressources cohérentes.

-   **`create_projet <NomProjet1> [NomProjet2 ...]`**
    Crée les ressources pour un ou plusieurs projets.

-   **`create_antenne <NomAntenne1> [NomAntenne2 ...]`**
    Crée les ressources pour une ou plusieurs antennes.

-   **`create_pole <NomPole1> [NomPole2 ...]`**
    Crée les ressources pour un ou plusieurs pôles.

### Synchronisation des droits

-   **`update_all_user_rights`**
    Synchronise les droits des utilisateurs en se basant sur leur appartenance aux canaux Mattermost. Cette commande **ajoute uniquement** des droits et n'en supprime jamais.

-   **`update_user_rights_and_remove`**
    Effectue une synchronisation complète : ajoute, met à jour et **supprime** les droits pour que les accès aux services externes correspondent exactement aux membres des canaux Mattermost.
    -   **Option** : `nocodb=false` pour ignorer la synchronisation avec NoCoDB.

### Autres commandes

-   **`send_email <Sujet> /// <Message>`**
    Envoie un email via Brevo à la liste de contacts associée à l'entité du canal. La commande doit être exécutée depuis un canal "admin".

-   **`help`**
    Affiche la liste des commandes disponibles.

## Lancer le bot

Pour démarrer le bot :

```bash
python -m app.bot
```

## Développement

### Tests

```bash
python -m unittest discover -s app/tests
```

### Pre-commit hooks

Ce projet utilise des `pre-commit hooks` pour garantir la qualité et la cohérence du code. Pour les installer :

```bash
pre-commit install
```

## Running with Docker

To build and run the bot using Docker, follow these steps.

### 1. Build the Docker Image

From the root (where the `Dockerfile` is located), run the following command to build the Docker image:

```bash
docker build -t marty-bot .
```

### 2. Run the Docker Container

Once the image is built, you can run it as a container. Make sure you have a `.env` file with your configuration in the root.

```bash
docker run -d --name marty-bot-container --env-file .env marty-bot
```

*   `-d`: Runs the container in detached mode (in the background).
*   `--name marty-bot-container`: Assigns a name to the container for easier management.
*   `--env-file .env`: Passes the environment variables from your `.env` file to the container.

To view the logs of the running container:

```bash
docker logs -f marty-bot-container
```

### 3. Using Docker Compose

Alternatively, you can use the provided `docker-compose.yml` file to manage the bot's container. This is the recommended method for running the bot in production.

First, ensure you have a complete `.env` file in the root directory. Then, you can start the bot with:

```bash
docker-compose up -d
```

This command will build the image (if it doesn't exist) and start the container in the background.

To view the logs:

```bash
docker-compose logs -f
```

To stop the bot:

```bash
docker-compose down
```
