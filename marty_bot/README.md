# Marty Bot

Marty Bot is a helpful assistant for managing Mattermost, Authentik, and Outline.

## Setup

### 1. Environment Variables

Configuration for Marty Bot is managed via environment variables.

1.  Copy the example environment file:
    ```bash
    cp .env.example .env
    ```
2.  Edit the `.env` file and provide your specific values for:
    *   `MATTERMOST_URL`: Your Mattermost instance URL (e.g., `https://your.mattermost.com` or `http://localhost:8065`). This is the base URL for API calls and WebSocket connection.
    *   `MATTERMOST_TEAM_ID`: The ID of the Mattermost team where new channels created by the bot will be placed.
    *   `BOT_TOKEN`: The token for your Mattermost bot account. This token is used for connecting to the WebSocket API (to receive messages), for posting messages as the bot, and for performing API actions such as creating channels. **Ensure the bot account has the appropriate permissions in Mattermost for these actions (e.g., channel creation).**
    *   `BOT_NAME`: The username of your bot in Mattermost, without the leading `@` (e.g., `marty`). The bot listens for messages mentioning this name.
    *   `AUTHENTIK_URL`: Your Authentik instance URL (e.g., `https://authentik.yourdomain.com`).
    *   `AUTHENTIK_TOKEN`: Your Authentik API token with permissions to create groups.
    *   `OUTLINE_URL`: Your Outline instance URL (e.g., `https://app.getoutline.com` or your self-hosted instance URL).
    *   `OUTLINE_TOKEN`: Your Outline API token with permissions to create collections.
    *   `NOCODB_URL`: (Optional) Your NoCoDB instance URL (e.g., `https://nocodb.yourdomain.com`). Required if NoCoDB integration is used.
    *   `NOCODB_TOKEN`: (Optional) Your NoCoDB API Token (from Account Settings -> API Tokens). Required if NoCoDB integration is used.
    *   `LOG_LEVEL`: (Optional) Set the logging level for the bot (e.g., `INFO`, `DEBUG`, `WARNING`, `ERROR`). Defaults to `INFO` if not set. Note: `DEBUG` level here is for Python's `logging` module.
    *   `DEBUG`: (Optional) Set to `true` to enable specific debug features in the bot, such as more verbose logging output distinct from `LOG_LEVEL` (e.g., raw WebSocket messages, detailed API payloads). Defaults to `false`. Example: `DEBUG=true`

**Important**: The `.env` file contains sensitive credentials and is included in `.gitignore` to prevent accidental commits. Keep your `.env` file secure and do not commit it to your repository.

The `.env.example` file in the repository shows all required variables with placeholder values.

### 2. Install Dependencies

First, ensure you have Python 3.8+ installed. Then, navigate to the project's root directory (where `requirements.txt` is located) and install the required packages:

```bash
pip install -r requirements.txt
```

## Running the Bot

To run Marty Bot directly:

```bash
python -m app.bot
```

This command executes the `if __name__ == "__main__":` block in `app/bot.py`, which initializes and starts the bot.

You should see log output in your console indicating the bot is attempting to connect to your Mattermost instance via WebSocket. If `DEBUG=true` is set in your `.env` file, you will see more verbose logging.

The bot runs as a standalone Python application.

## Commands

Marty Bot supports various commands to manage resources across integrated services.

### Resource Creation Commands

These commands create associated resources (groups, channels, collections, etc.) in Authentik, Outline, Mattermost, Brevo, and NoCoDB (where applicable based on entity type and configuration).

*   **`create_projet <NomProjet1> [NomProjet2 ...]`**
    *   Creates resources for one or more projects.
    *   For each project, it typically creates:
        *   Authentik groups (standard and admin).
        *   Mattermost channels (standard and admin).
        *   An Outline collection.
        *   A Brevo contact list.
        *   *NoCoDB bases are NOT created for projects.*
    *   Example: `@marty create_projet MonSuperProjet AutreProjetCool`

*   **`create_antenne <NomAntenne1> [NomAntenne2 ...]`**
    *   Creates resources for one or more "antennes" (branches/local groups).
    *   Similar resources as `create_projet`, but also:
        *   Creates a NoCoDB base for each antenne.
    *   Example: `@marty create_antenne AntenneParis AntenneLyon`

*   **`create_pole <NomPole1> [NomPole2 ...]`**
    *   Creates resources for one or more "pôles" (departments/teams).
    *   Similar resources as `create_projet`, but also:
        *   Creates a NoCoDB base for each pôle.
    *   Example: `@marty create_pole PoleTechnique PoleCommunication`

The bot will send a confirmation message back to the channel detailing the actions taken for each created entity. The user issuing the command will typically be added to the created Mattermost channels.

### User Rights Synchronization Commands

These commands manage user access rights across the integrated services based on their membership in Mattermost channels.

*   **`update_all_user_rights`**
    *   Ensures users in Mattermost channels have corresponding access in Authentik, Outline, Brevo lists, and NoCoDB bases (for Antennes/Pôles).
    *   This command **only adds or updates** permissions. It never removes access.
    *   Useful for quickly granting rights after adding users to Mattermost channels.

*   **`update_user_rights_and_remove`**
    *   Performs a full synchronization. It ensures that access in Authentik, Outline, Brevo, and NoCoDB exactly mirrors Mattermost channel memberships.
    *   This means it will **add, update, AND remove** access rights if users are no longer in the relevant Mattermost channels or if their roles (admin vs. standard channel) change.
    *   This is the command for a complete consistency check but may take longer.
    *   **Option :** `nocodb=false`
        *   Ajoutez `nocodb=false` comme argument pour que cette commande ignore complètement la synchronisation des bases de données NoCoDB.
        *   Exemple : `@marty update_user_rights_and_remove nocodb=false`

### Email Command

*   **`send_email <Sujet> /// <Message>`**
    *   Sends an email via Brevo to the contact list associated with the "standard" channel of the current entity (projet, antenne, or pôle).
    *   Must be run from the "admin" Mattermost channel of the entity.
    *   The subject and the email body (which can be Markdown) are separated by `///`.
    *   Example: `@marty send_email Annonce Importante /// Bonjour à tous, voici une nouvelle importante...`

### Help Command

*   **`help`**
    *   Displays a help message listing all available commands and their descriptions.
    *   Example: `@marty help`

## Running Tests

To run the unit tests, navigate to the root directory of the project (`marty_bot/`) and run the following command:

```bash
python -m unittest discover -s app/tests
```

Ensure that your environment is set up correctly, as some tests might interact with configuration loading (though API calls themselves are mocked). For example, having a `.env` file with placeholder values for all expected variables can prevent import errors in `app.config` if it's loaded when test files are discovered or imported. The tests for client modules specifically mock out the `config` values they use at runtime to ensure isolation.

## Developer Setup: Code Quality & Pre-commit Hooks

This project uses pre-commit hooks to enforce code style and quality (linting and formatting) automatically before each commit. This helps maintain a consistent codebase.

### Initial Setup

1.  **Install development dependencies:**
    If you haven't already, install the dependencies listed in `requirements-dev.txt` (which includes `pre-commit`, `black`, and `flake8`). This file is located in the project root (`marty_bot/`).
    ```bash
    pip install -r requirements-dev.txt
    ```
    It's recommended to do this in your project's virtual environment.

2.  **Install Git hooks:**
    From the root directory of the project (`marty_bot/`), run:
    ```bash
    pre-commit install
    ```
    This command sets up the pre-commit script to run automatically when you `git commit`.

### How it Works

Once installed, `pre-commit` will run the configured hooks (like Black for formatting and Flake8 for linting) on any changed files before your commit is finalized.

*   If any hooks modify your files (e.g., Black reformats your code), the commit will be aborted. You'll need to `git add` the modified files and try committing again.
*   If any hooks report errors (e.g., Flake8 finds linting issues), the commit will be aborted. You'll need to fix the reported issues, `git add` your changes, and try committing again.

### Running Hooks Manually

You can also run the pre-commit hooks manually on all files at any time:
```bash
pre-commit run --all-files
```
This is useful for checking the entire codebase or after making larger changes.

Our Flake8 configuration is managed in the `.flake8` file (located in `marty_bot/`), and Black's configuration is in `.pre-commit-config.yaml`.
