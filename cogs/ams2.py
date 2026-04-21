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
    # Fallback: first lap entry has DriverName
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
            embeds.append(_build_result_embed(entry, result))

        if embeds:
            await interaction.followup.send(embeds=embeds)
        else:
            await interaction.followup.send("No results could be loaded.")

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

def _build_result_embed(entry: dict, result: dict) -> discord.Embed:
    raw_date = entry.get("date") or result.get("Date") or ""
    try:
        dt = datetime.datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
        date_str = dt.strftime("%d %b %Y")
    except Exception:
        date_str = raw_date

    places: list[dict] = result.get("Places") or []
    places = sorted(places, key=lambda p: p.get("Position", 99))

    # Determine race class (all finishers are usually the same class)
    race_class = places[0].get("Class", "") if places else ""
    lap_counts = [len(p.get("Laps") or []) for p in places]
    leader_laps = max(lap_counts) if lap_counts else 0

    title = f"Race Result — {date_str}"
    if race_class:
        title += f"  |  {race_class}"

    embed = discord.Embed(title=title, colour=discord.Colour.gold())

    # Leader's total time for gap calculations
    leader_ms: int | None = None
    if places:
        raw = places[0].get("TotalRaceTime")
        if raw:
            leader_ms = _ns_to_ms(raw)

    # --- Finishers ---
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
        dsq_str = " ~~DSQ~~" if dsq else ""

        if dsq:
            time_str = "DSQ"
        elif laps < leader_laps:
            laps_down = leader_laps - laps
            lap_word = "lap" if laps_down == 1 else "laps"
            time_str = f"+{laps_down} {lap_word}"
        elif leader_ms is not None and total_ms is not None and pos > 1:
            gap = total_ms - leader_ms
            time_str = _format_ms(gap, sign=True)
        else:
            time_str = _format_ms(total_ms)

        if penalty_ms:
            time_str += f" (pen +{_format_ms(penalty_ms)})"

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


def _build_standings_embed(championship_id: str, data: dict) -> discord.Embed:
    name = (
        data.get("name") or data.get("Name")
        or data.get("championshipName") or f"Championship `{championship_id}`"
    )
    embed = discord.Embed(
        title=f"Standings — {name}",
        colour=discord.Colour.blue(),
    )

    drivers: list[dict] = data.get("drivers") or data.get("Drivers") or data.get("driverStandings") or []

    def _pos(d: dict) -> int:
        return d.get("position") or d.get("Position") or d.get("classPosition") or 99

    def _pts(d: dict) -> int | float:
        return d.get("points") or d.get("Points") or 0

    def _name(d: dict) -> str:
        driver = d.get("driver") or d.get("Driver") or {}
        if isinstance(driver, dict):
            n = driver.get("name") or driver.get("Name") or ""
        else:
            n = str(driver)
        return n or d.get("name") or d.get("Name") or "Unknown"

    lines = []
    for d in sorted(drivers, key=_pos)[:25]:
        lines.append(f"{_position_emoji(_pos(d))} **{_name(d)}** — {_pts(d)} pts")

    if lines:
        embed.add_field(name="Drivers", value="\n".join(lines), inline=False)
    else:
        embed.description = "No standings data available yet."

    teams: list[dict] = data.get("teams") or data.get("Teams") or data.get("teamStandings") or []
    if teams:
        team_lines = []
        for i, t in enumerate(sorted(teams, key=_pos)[:10], 1):
            tname = t.get("name") or t.get("Name") or t.get("team") or "Unknown"
            pts = t.get("points") or t.get("Points") or 0
            team_lines.append(f"`{i:>2}.` {tname} — {pts} pts")
        embed.add_field(name="Teams", value="\n".join(team_lines), inline=False)

    return embed


async def setup(bot: commands.Bot):
    base_url = os.environ["AMS2SM_BASE_URL"]
    client = AMS2Client(base_url)
    await bot.add_cog(AMS2Cog(bot, client))
