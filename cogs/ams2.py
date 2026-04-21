import discord
from discord import app_commands
from discord.ext import commands
from api.client import AMS2Client
import os
import datetime


def _format_time_ms(ms: int | float | None) -> str:
    """Convert milliseconds to M:SS.mmm string."""
    if ms is None or ms <= 0:
        return "—"
    ms = int(ms)
    minutes, remainder = divmod(ms, 60000)
    seconds, millis = divmod(remainder, 1000)
    if minutes:
        return f"{minutes}:{seconds:02d}.{millis:03d}"
    return f"{seconds}.{millis:03d}"


def _driver_name(member: dict) -> str:
    driver = member.get("driver") or member.get("Driver") or {}
    if isinstance(driver, dict):
        name = driver.get("name") or driver.get("Name") or ""
    else:
        name = str(driver)
    return name or member.get("name") or member.get("Name") or "Unknown"


def _position_emoji(pos: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(pos, f"`{pos:>2}`")


class AMS2Cog(commands.Cog):
    def __init__(self, bot: commands.Bot, client: AMS2Client):
        self.bot = bot
        self.client = client

    # ── /results ──────────────────────────────────────────────────────────────

    @app_commands.command(name="results", description="Show the most recent race result")
    @app_commands.describe(count="Number of recent results to list (default 1, max 5)")
    async def results(self, interaction: discord.Interaction, count: int = 1):
        await interaction.response.defer()
        count = max(1, min(count, 5))

        try:
            listing = await self.client.list_results(page=1)
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch results: {e}")
            return

        entries = listing.get("results", [])
        if not entries:
            await interaction.followup.send("No results found on the server.")
            return

        embeds = []
        for entry in entries[:count]:
            url = (
                entry.get("results_json_url")
                or entry.get("url")
                or entry.get("ResultFile")
                or entry.get("File")
                or ""
            )
            try:
                result = await self.client.get_result(url)
            except Exception as e:
                await interaction.followup.send(f"Failed to fetch result detail: {e}")
                return

            embed = _build_result_embed(entry, result)
            embeds.append(embed)

        await interaction.followup.send(embeds=embeds)

    # ── /standings ────────────────────────────────────────────────────────────

    @app_commands.command(name="standings", description="Show championship standings")
    @app_commands.describe(championship_id="Championship ID (use /championships to find IDs)")
    async def standings(self, interaction: discord.Interaction, championship_id: str):
        await interaction.response.defer()
        try:
            data = await self.client.get_championship_standings(championship_id)
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch standings: {e}")
            return

        embed = _build_standings_embed(championship_id, data)
        await interaction.followup.send(embed=embed)

    # ── /championships ────────────────────────────────────────────────────────

    @app_commands.command(name="championships", description="List available championships")
    async def championships(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            champs = await self.client.list_championships()
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch championships: {e}")
            return

        if not champs:
            await interaction.followup.send("No championships found.")
            return

        lines = []
        for c in champs:
            cid = c.get("id") or c.get("ID") or c.get("championshipId") or "?"
            name = c.get("name") or c.get("Name") or c.get("title") or "Unnamed"
            lines.append(f"**{name}** — ID: `{cid}`")

        embed = discord.Embed(
            title="Championships",
            description="\n".join(lines),
            colour=discord.Colour.blue(),
        )
        await interaction.followup.send(embed=embed)

    # ── /status ───────────────────────────────────────────────────────────────

    @app_commands.command(name="status", description="Show AMS2 server manager health")
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            data = await self.client.healthcheck()
        except Exception as e:
            await interaction.followup.send(f"Server unreachable: {e}")
            return

        embed = discord.Embed(title="Server Status", colour=discord.Colour.green())
        for key, value in data.items():
            embed.add_field(name=key, value=str(value), inline=True)
        await interaction.followup.send(embed=embed)


# ── Embed builders ─────────────────────────────────────────────────────────────

def _build_result_embed(entry: dict, result: dict) -> discord.Embed:
    # Try to pull track/session info from both the listing entry and the result body
    track = (
        entry.get("track") or entry.get("Track")
        or result.get("TrackVariation") or result.get("track")
        or result.get("trackName") or result.get("track_name") or "Unknown Track"
    )
    session_type = (
        entry.get("sessionType") or entry.get("session_type") or entry.get("SessionType")
        or result.get("sessionType") or result.get("session_type") or result.get("SessionType")
        or "Race"
    )
    raw_date = (
        entry.get("date") or entry.get("Date")
        or result.get("startTime") or result.get("start_time") or result.get("StartTime") or ""
    )
    try:
        dt = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        date_str = dt.strftime("%d %b %Y  %H:%M UTC")
    except Exception:
        date_str = raw_date or "Unknown date"

    embed = discord.Embed(
        title=f"{session_type} — {track}",
        description=date_str,
        colour=discord.Colour.gold(),
    )

    # Normalise participant list across known formats
    participants = (
        result.get("Result", {}).get("Members")
        or result.get("participants")
        or result.get("Participants")
        or result.get("members")
        or []
    )

    # Sort by finishing position
    def _finish_pos(p):
        return (
            p.get("RacePosition") or p.get("racePosition")
            or p.get("finishingPosition") or p.get("position")
            or p.get("Position") or 99
        )

    participants = sorted(participants, key=_finish_pos)

    lines = []
    fastest_lap = None
    fastest_driver = None

    for p in participants[:20]:
        pos = _finish_pos(p)
        name = _driver_name(p)
        car = p.get("carName") or p.get("CarName") or p.get("vehicleName") or ""
        total_ms = (
            p.get("TotalTime") or p.get("totalTime")
            or p.get("raceTime") or p.get("RaceTime")
        )
        fl_ms = p.get("FastestLapTime") or p.get("fastestLapTime") or p.get("fastestLap")

        if fl_ms and (fastest_lap is None or fl_ms < fastest_lap):
            fastest_lap = fl_ms
            fastest_driver = name

        time_str = _format_time_ms(total_ms)
        car_str = f" ({car})" if car else ""
        lines.append(f"{_position_emoji(pos)} {name}{car_str} — {time_str}")

    if lines:
        embed.add_field(name="Finishers", value="\n".join(lines), inline=False)

    if fastest_driver:
        embed.set_footer(text=f"Fastest lap: {fastest_driver}  {_format_time_ms(fastest_lap)}")

    return embed


def _build_standings_embed(championship_id: str, data: dict) -> discord.Embed:
    name = data.get("name") or data.get("Name") or data.get("championshipName") or championship_id
    embed = discord.Embed(
        title=f"Championship Standings — {name}",
        colour=discord.Colour.blue(),
    )

    # Driver standings
    drivers = data.get("drivers") or data.get("Drivers") or data.get("driverStandings") or []

    def _standing_pos(d):
        return (
            d.get("position") or d.get("Position")
            or d.get("classPosition") or 99
        )

    drivers = sorted(drivers, key=_standing_pos)

    lines = []
    for d in drivers[:25]:
        pos = _standing_pos(d)
        driver_name = _driver_name(d)
        pts = d.get("points") or d.get("Points") or 0
        lines.append(f"{_position_emoji(pos)} **{driver_name}** — {pts} pts")

    if lines:
        embed.add_field(name="Drivers", value="\n".join(lines), inline=False)
    else:
        embed.description = "No standings data available yet."

    # Team standings (optional)
    teams = data.get("teams") or data.get("Teams") or data.get("teamStandings") or []
    if teams:
        team_lines = []
        for i, t in enumerate(sorted(teams, key=_standing_pos)[:10], 1):
            tname = t.get("name") or t.get("Name") or t.get("team") or "Unknown"
            pts = t.get("points") or t.get("Points") or 0
            team_lines.append(f"`{i:>2}` {tname} — {pts} pts")
        embed.add_field(name="Teams", value="\n".join(team_lines), inline=False)

    return embed


async def setup(bot: commands.Bot):
    base_url = os.environ["AMS2SM_BASE_URL"]
    client = AMS2Client(base_url)
    await bot.add_cog(AMS2Cog(bot, client))
