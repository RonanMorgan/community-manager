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
    *   `MATTERMOST_TOKEN`: An admin-level API token for Mattermost. This token is used by the `MattermostClient` for administrative actions like creating channels. It needs permissions to manage channels on the specified team.
    *   `MATTERMOST_TEAM_ID`: The ID of the Mattermost team where new channels created by the bot will be placed.
    *   `BOT_TOKEN`: The personal access token for the Mattermost bot account itself. This token is used for connecting to the Mattermost WebSocket API (for receiving messages) and for posting messages back to channels as the bot.
    *   `BOT_NAME`: The username of your bot in Mattermost, without the leading `@` (e.g., `marty`). The bot listens for messages mentioning this name.
    *   `AUTHENTIK_URL`: Your Authentik instance URL (e.g., `https://authentik.yourdomain.com`).
    *   `AUTHENTIK_TOKEN`: Your Authentik API token with permissions to create groups.
    *   `OUTLINE_URL`: Your Outline instance URL (e.g., `https://app.getoutline.com` or your self-hosted instance URL).
    *   `OUTLINE_TOKEN`: Your Outline API token with permissions to create collections.
    *   `LOG_LEVEL`: (Optional) Set the logging level for the bot (e.g., `INFO`, `DEBUG`, `WARNING`, `ERROR`). Defaults to `INFO` if not set.

**Important**: The `.env` file contains sensitive credentials and is included in `.gitignore` to prevent accidental commits. Keep your `.env` file secure and do not commit it to your repository.

The `.env.example` file in the repository shows all required variables with placeholder values.

### 2. Install Dependencies

First, ensure you have Python 3.8+ installed. Then, navigate to the project's root directory (where `requirements.txt` is located) and install the required packages:

```bash
pip install -r requirements.txt
```

## Running the Bot

To run Marty Bot, use Uvicorn:

```bash
uvicorn app.main:app --reload
```

This will start the FastAPI server, and the Mattermost bot will connect in the background. The `--reload` flag is useful for development as it automatically reloads the server when code changes are detected.

You should see output indicating the bot has connected to your Mattermost instance via WebSocket.

## Commands

### `create_group`

This command allows you to create associated groups/channels in Authentik, Outline, and Mattermost.

**Usage:**

`@<BOT_NAME> create_group <project_name>`

**Example:**

If your bot's name is `marty`, to create a group for a project named "alpha_squad", you would type:

`@marty create_group alpha_squad`

The bot will then (eventually) perform the following actions:
- Create a group in Authentik named `project_name`.
- Create a collection/group in Outline for `project_name`.
- Create a new channel in Mattermost for `project_name`.

It will send a confirmation message back to the channel where the command was issued.

## Running Tests

To run the unit tests, navigate to the root directory of the project (`marty_bot/`) and run the following command:

```bash
python -m unittest discover -s app/tests
```

Ensure that your environment is set up correctly, as some tests might interact with configuration loading (though API calls themselves are mocked). For example, having a `.env` file with placeholder values for all expected variables can prevent import errors in `app.config` if it's loaded when test files are discovered or imported. The tests for client modules specifically mock out the `config` values they use at runtime to ensure isolation.
