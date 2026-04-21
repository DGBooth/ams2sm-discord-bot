# ams2sm-discord-bot

A Discord bot that queries an [Emperor Servers AMS2 Server Manager](https://emperorservers.com/products/automobilista-2-server-manager) instance to surface race results and championship standings in Discord.

## Commands

| Command | Description |
|---|---|
| `/results [count]` | Show the most recent race result(s). `count` defaults to 1, max 5. |
| `/standings <championship_id>` | Show driver (and team) standings for a championship. |
| `/championships` | List available championships and their IDs. |
| `/status` | Show the server manager health status. |

## Setup

### 1. Create a Discord application & bot

1. Go to https://discord.com/developers/applications and create a new application.
2. Under **Bot**, create a bot and copy the token.
3. Under **OAuth2 → URL Generator**, select scopes `bot` + `applications.commands`, and the `Send Messages` permission. Use the generated URL to invite the bot to your server.

### 2. Configure the bot

```bash
cp .env.example .env
# Edit .env and set DISCORD_TOKEN and AMS2SM_BASE_URL
```

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

## AMS2 Server Manager permissions

The API endpoints used are:
- `GET /healthcheck.json` — public
- `GET /api/results` — requires "Results - View" permission (enable Public Access or create a bot account)
- `GET /api/championship/{id}/standings.json` — requires "Championships - Api Standings" permission

Make sure the relevant permissions are set to **Public Access** in your Server Manager accounts settings, or create a dedicated account and add its credentials to `.env`.

## Rate limiting

The Emperor Servers API limits to **5 requests per 20 seconds**. The bot makes at most 2 requests per user command, so normal use is well within limits.
