import discord
from discord import app_commands
from discord.ext import commands
from api.client import AMS2Client
import os
import datetime


def _ns_to_ms(ns: int | float) -> int:
    return int(ns) // 1_000_000


def _format_ms(ms: int | None, sign: bool = False) -> str:
    """Format milliseconds as [+]M:SS.mmm or SS.mmm."""
    if ms is None or ms < 0:
        return "—"
    prefix = "+" if sign else ""
    minutes, remainder = divmod(ms, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    if minutes:
        return f"{prefix}{minutes}:{seconds:02d}.{millis:03d}"
    return f"{prefix}{seconds}.{millis:03d}"


def _position_emoji(pos: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(pos, f"`P{pos}`")


def _driver_name(place: dict) -> str:
    drivers = place.get("Drivers") or []
    if drivers:
        return drivers[0].get("Name") or "Unknown"
    laps = place.get("Laps") or []
    if laps:
        return laps[0].get("DriverName") or "Unknown"
    return "Unknown"


def _fastest_valid_lap_ms(place: dict) -> int | None:
    best = None
    for lap in place.get("Laps") or []:
        if lap.get("Valid") and lap.get("Time", 0) > 0:
            ms = _ns_to_ms(lap["Time"])
            if best is None or ms < best:
                best = ms
    return best


class AMS2Cog(commands.Cog):
    def __init__(self, bot: commands.Bot, client: AMS2Client):
        self.bot = bot
        self.client = client

    async def cog_load(self):
        if self.client.game_server_url:
            try:
                await self.client.fetch_track_names()
                print(f"Loaded {len(self.client._track_names)} track names")
            except Exception as e:
                print(f"Warning: could not load track names: {e}")
        else:
            print("AMS2_GAME_SERVER_URL not set — track names and /session unavailable")

    # ── /results ──────────────────────────────────────────────────────────────

    @app_commands.command(name="results", description="Show the most recent race result(s)")
    @app_commands.describe(count="Number of recent races to show (default 1, max 5)")
    async def results(self, interaction: discord.Interaction, count: int = 1):
        await interaction.response.defer()
        count = max(1, min(count, 5))

        try:
            entries = await self.client.list_race_results(count=count)
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch results list: {e}")
            return

        if not entries:
            await interaction.followup.send("No race results found.")
            return

        embeds = []
        for entry in entries:
            url = entry.get("server_manager_results_json_url") or ""
            if not url:
                continue
            try:
                result = await self.client.get_result(url)
            except Exception as e:
                await interaction.followup.send(f"Failed to fetch result detail: {e}")
                return
            embeds.append(_build_result_embed(self.client, entry, result))

        if embeds:
            await interaction.followup.send(embeds=embeds)
        else:
            await interaction.followup.send("No results could be loaded.")

    # ── /session ──────────────────────────────────────────────────────────────

    @app_commands.command(name="session", description="Show the current live server session")
    async def session(self, interaction: discord.Interaction):
        if not self.client.game_server_url:
            await interaction.response.send_message(
                "Live session info is not available — `AMS2_GAME_SERVER_URL` is not configured.",
                ephemeral=True,
            )
            return
        await interaction.response.defer()
        try:
            data = await self.client.session_status(members=True, participants=True)
        except Exception as e:
            await interaction.followup.send(f"Could not reach game server: {e}")
            return

        embed = _build_session_embed(self.client, data)
        await interaction.followup.send(embed=embed)

    # ── /standings ────────────────────────────────────────────────────────────

    @app_commands.command(name="standings", description="Show championship standings from the most recent race")
    async def standings(self, interaction: discord.Interaction):
        await interaction.response.defer()

        try:
            entries = await self.client.list_race_results(count=1)
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch results: {e}")
            return

        if not entries:
            await interaction.followup.send("No race results found.")
            return

        try:
            result = await self.client.get_result(entries[0]["server_manager_results_json_url"])
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch result detail: {e}")
            return

        championship_id = result.get("ChampionshipID")
        if not championship_id:
            await interaction.followup.send("The most recent race is not part of a championship.")
            return

        try:
            data = await self.client.get_championship_standings(championship_id)
        except Exception as e:
            await interaction.followup.send(f"Failed to fetch standings: {e}")
            return

        embed = _build_standings_embed(championship_id, data)
        await interaction.followup.send(embed=embed)

    # ── /championships ────────────────────────────────────────────────────────

    @app_commands.command(name="championships", description="List available championships and their IDs")
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
            lines.append(f"**{name}**\n`{cid}`")

        embed = discord.Embed(
            title="Championships",
            description="\n\n".join(lines),
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

def _build_result_embed(client: AMS2Client, entry: dict, result: dict) -> discord.Embed:
    raw_date = entry.get("date") or result.get("Date") or ""
    try:
        dt = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        date_str = dt.strftime("%d %b %Y")
    except Exception:
        date_str = raw_date

    places: list[dict] = result.get("Places") or []
    places = sorted(places, key=lambda p: p.get("Position", 99))

    race_class = places[0].get("Class", "") if places else ""
    lap_counts = [len(p.get("Laps") or []) for p in places]
    leader_laps = max(lap_counts) if lap_counts else 0

    track_id = str(result.get("TrackID") or entry.get("track") or "")
    track_name = client.resolve_track(track_id) if track_id else "Unknown Track"

    title = f"Race Result — {track_name}  |  {date_str}"
    if race_class:
        title += f"  |  {race_class}"

    embed = discord.Embed(title=title, colour=discord.Colour.gold())

    leader_ms: int | None = None
    if places:
        raw = places[0].get("TotalRaceTime")
        if raw:
            leader_ms = _ns_to_ms(raw)

    lines = []
    overall_fastest_ms: int | None = None
    overall_fastest_driver = ""

    for p in places:
        pos = p.get("Position", 99)
        name = _driver_name(p)
        car = p.get("CarModel") or ""
        laps = len(p.get("Laps") or [])
        dsq = p.get("Disqualified", False)
        total_ns = p.get("TotalRaceTime")
        total_ms = _ns_to_ms(total_ns) if total_ns else None
        penalty_ns = p.get("TimePenalty") or 0
        penalty_ms = _ns_to_ms(penalty_ns) if penalty_ns > 0 else 0

        fl_ms = _fastest_valid_lap_ms(p)
        if fl_ms and (overall_fastest_ms is None or fl_ms < overall_fastest_ms):
            overall_fastest_ms = fl_ms
            overall_fastest_driver = name

        pos_str = _position_emoji(pos)
        car_str = f" *({car})*" if car else ""

        if dsq:
            time_str = "DSQ"
        elif laps < leader_laps:
            laps_down = leader_laps - laps
            time_str = f"+{laps_down} {'lap' if laps_down == 1 else 'laps'}"
        elif leader_ms is not None and total_ms is not None and pos > 1:
            time_str = _format_ms(total_ms - leader_ms, sign=True)
        else:
            time_str = _format_ms(total_ms)

        if penalty_ms:
            time_str += f" (pen +{_format_ms(penalty_ms)})"

        dsq_str = " ~~DSQ~~" if dsq else ""
        lines.append(f"{pos_str} **{name}**{car_str}{dsq_str} — {time_str}")

    if lines:
        embed.add_field(name=f"Results  ({leader_laps} laps)", value="\n".join(lines), inline=False)
    else:
        embed.description = "No finishers recorded."

    footer_parts = []
    if overall_fastest_driver:
        footer_parts.append(f"Fastest lap: {overall_fastest_driver}  {_format_ms(overall_fastest_ms)}")
    champ_id = result.get("ChampionshipID") or ""
    if champ_id:
        footer_parts.append(f"Championship: {champ_id}")
    if footer_parts:
        embed.set_footer(text="  •  ".join(footer_parts))

    return embed


def _build_session_embed(client: AMS2Client, data: dict) -> discord.Embed:
    attrs = data.get("attributes") or {}

    def attr(key: str, default: str = "—") -> str:
        v = attrs.get(key)
        return str(v) if v is not None else default

    session_state = attr("sessionState", "Unknown")
    session_type = attr("sessionType", "Unknown")
    track_id = str(data.get("trackId") or attrs.get("trackId") or attrs.get("track") or "")
    track_name = client.resolve_track(track_id) if track_id else attr("trackName", "Unknown")

    colour = {"Race": discord.Colour.red(), "Qualifying": discord.Colour.orange(),
              "Practice": discord.Colour.green()}.get(session_type, discord.Colour.greyple())

    embed = discord.Embed(
        title=f"{session_type} — {track_name}",
        description=f"State: **{session_state}**",
        colour=colour,
    )

    members: list[dict] = data.get("members") or []
    if members:
        lines = []
        for m in members:
            name = m.get("name") or "Unknown"
            state = m.get("state") or ""
            lines.append(f"• **{name}**" + (f"  *{state}*" if state else ""))
        embed.add_field(name=f"Drivers ({len(members)})", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Drivers", value="No one connected", inline=False)

    return embed


def _build_standings_embed(championship_id: str, data: dict) -> discord.Embed:
    embed = discord.Embed(
        title=f"Championship Standings",
        colour=discord.Colour.blue(),
    )

    # DriverStandings is a dict keyed by class name (empty string = default)
    driver_standings: dict = data.get("DriverStandings") or {}

    for class_name, drivers in driver_standings.items():
        if not drivers:
            continue

        # Filter out AI/non-players and sort by position
        drivers = [d for d in drivers if d.get("IsPlayer", True)]
        drivers = sorted(drivers, key=lambda d: d.get("Position", 99))

        lines = []
        for d in drivers[:25]:
            pos = d.get("Position", 99)
            name = d.get("DriverName") or "Unknown"
            pts = d.get("Points", 0)
            penalty = d.get("PointsPenalty", 0)
            pts_str = str(pts)
            if penalty:
                pts_str += f" (-{penalty})"
            lines.append(f"{_position_emoji(pos)} **{name}** — {pts_str} pts")

        field_name = f"Drivers — {class_name}" if class_name else "Drivers"
        embed.add_field(name=field_name, value="\n".join(lines), inline=False)

    if not embed.fields:
        embed.description = "No standings data available yet."

    # TeamStandings is also a dict keyed by class; values may be null
    team_standings: dict = data.get("TeamStandings") or {}
    for class_name, teams in team_standings.items():
        if not teams:
            continue
        teams = sorted(teams, key=lambda t: t.get("Position", 99))
        team_lines = []
        for t in teams[:10]:
            pos = t.get("Position", 99)
            tname = t.get("TeamName") or t.get("name") or "Unknown"
            pts = t.get("Points", 0)
            team_lines.append(f"{_position_emoji(pos)} {tname} — {pts} pts")
        field_name = f"Teams — {class_name}" if class_name else "Teams"
        embed.add_field(name=field_name, value="\n".join(team_lines), inline=False)

    return embed


async def setup(bot: commands.Bot):
    base_url = os.environ["AMS2SM_BASE_URL"]
    game_server_url = os.environ.get("AMS2_GAME_SERVER_URL") or None
    client = AMS2Client(base_url, game_server_url=game_server_url)
    await bot.add_cog(AMS2Cog(bot, client))
