# Marty Bot

Marty Bot is a helpful assistant for managing Mattermost, Authentik, and Outline.

## Setup

### 1. Environment Variables

Create a `.env` file in the root of the project (`marty_bot/.env`) and add the following environment variables, replacing the placeholder values with your actual credentials and URLs:

```env
# Mattermost
MATTERMOST_URL=your_mattermost_url_e.g._http://localhost:8065
MATTERMOST_TOKEN=your_mattermost_admin_or_user_token_if_needed_for_other_ops
BOT_TOKEN=your_mattermost_bot_access_token
BOT_NAME=name_of_your_bot_in_mattermost_e.g._marty

# Authentik
AUTHENTIK_URL=your_authentik_url
AUTHENTIK_TOKEN=your_authentik_api_token

# Outline
OUTLINE_URL=your_outline_url
OUTLINE_TOKEN=your_outline_api_token
```

**Important:**
- `MATTERMOST_URL` should be the base URL of your Mattermost instance (e.g., `http://localhost:8065`).
- `BOT_TOKEN` is the personal access token for your bot account in Mattermost.
- `BOT_NAME` is the username of your bot in Mattermost (without the leading '@').

### 2. Install Dependencies

Ensure you have Python 3.8+ installed. Then, install the required packages:

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
