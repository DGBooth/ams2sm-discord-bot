# ams2sm-discord-bot

A Discord bot that queries an [Emperor Servers AMS2 Server Manager](https://emperorservers.com/products/automobilista-2-server-manager) instance to surface race results, championship standings, and live session info in Discord.

## Commands

| Command | Description |
|---|---|
| `/results [count]` | Show the most recent race result(s). `count` defaults to 1, max 5. |
| `/standings` | Show driver (and team) standings for the championship linked to the most recent race. |
| `/championships` | List available championships and their IDs. |
| `/session` | Show the current live server session and connected drivers. Requires `AMS2_GAME_SERVER_URL`. |
| `/status` | Show the server manager health status. |

## Setup

### 1. Create a Discord application & bot

1. Go to https://discord.com/developers/applications and create a new application.
2. Under **Bot**, create a bot and copy the token.
3. Under **OAuth2 → URL Generator**, select scopes `bot` + `applications.commands`, and the `Send Messages` permission. Use the generated URL to invite the bot to your server.

### 2. Configure the bot

```bash
cp .env.example .env
# Edit .env and set DISCORD_TOKEN, AMS2SM_BASE_URL, and optionally AMS2_GAME_SERVER_URL
```

| Variable | Required | Description |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Bot token from the Discord Developer Portal. |
| `AMS2SM_BASE_URL` | Yes | Base URL of your AMS2 Server Manager instance (no trailing slash). |
| `AMS2_GAME_SERVER_URL` | No | Direct URL of the AMS2 game server's built-in HTTP API (typically `http://<server-ip>:9000`). Enables `/session` and live track name resolution. |

### 3. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Run

```bash
python bot.py
```

The bot syncs slash commands globally on startup. Discord can take up to an hour to propagate global commands; for instant testing, see [guild-scoped sync](https://discordpy.readthedocs.io/en/stable/interactions/api.html#discord.app_commands.CommandTree.sync).

## Docker

```bash
cp .env.example .env
# fill in .env
docker compose up -d
```

The compose file uses `restart: unless-stopped`, so the bot will restart automatically if it crashes or the host reboots. The `.env` file is excluded from the image; it is injected at runtime via `env_file`.

## Track names

The bot ships with a static lookup table of ~180 known AMS2 track IDs (`api/tracks.py`). If `AMS2_GAME_SERVER_URL` is configured, names are also fetched live from the game server at startup and take precedence. Tracks not found in either source are displayed as their raw numeric ID.

## AMS2 Server Manager permissions

The API endpoints used are:

| Endpoint | Permission required |
|---|---|
| `GET /healthcheck.json` | Public |
| `GET /api/results/list.json` | Results — View |
| `GET /server/0/result/download/…` | Results — View |
| `GET /api/championship/{id}/standings.json` | Championships — Api Standings |
| `GET /api/championships` | Championships — View |

Make sure the relevant permissions are set to **Public Access** in your Server Manager account settings, or create a dedicated account with those permissions.

## Rate limiting

The Emperor Servers API limits to **5 requests per 20 seconds**. The bot makes at most 2 requests per user command, so normal use is well within limits.
