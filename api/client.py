import aiohttp
from typing import Optional
from api.tracks import TRACK_NAMES as _STATIC_TRACK_NAMES


class AMS2Client:
    def __init__(self, base_url: str, game_server_url: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.game_server_url = game_server_url.rstrip("/") if game_server_url else None
        self._session: Optional[aiohttp.ClientSession] = None
        self._track_names: dict[str, str] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, base: str, path: str, params: dict = None) -> dict | list:
        session = await self._get_session()
        url = f"{base}{path}"
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    def _sm(self, path: str, params: dict = None):
        """GET from the Server Manager."""
        return self._get(self.base_url, path, params)

    def _gs(self, path: str, params: dict = None):
        """GET from the AMS2 game server's built-in API. Raises if not configured."""
        if not self.game_server_url:
            raise RuntimeError("AMS2_GAME_SERVER_URL is not configured")
        return self._get(self.game_server_url, path, params)

    # ── Server Manager endpoints ───────────────────────────────────────────────

    async def healthcheck(self) -> dict:
        return await self._sm("/healthcheck.json")

    async def list_results(self, page: int = 0, search: str = None) -> dict:
        """List results. Page is 0-indexed."""
        params = {"page": page}
        if search:
            params["q"] = search
        return await self._sm("/api/results/list.json", params)

    async def get_result(self, url: str) -> dict:
        """Fetch a result file by its server_manager_results_json_url path."""
        path = url if url.startswith("/") else f"/server/0/result/download/{url}"
        return await self._sm(path)

    async def list_race_results(self, count: int = 1) -> list[dict]:
        """Return up to `count` Race-session entries, searching across pages."""
        found = []
        page = 0
        while len(found) < count:
            listing = await self.list_results(page=page)
            entries = listing.get("results", [])
            if not entries:
                break
            for entry in entries:
                if entry.get("manager_session_type", "").lower() == "race":
                    found.append(entry)
                    if len(found) == count:
                        break
            if page >= listing.get("num_pages", 1) - 1:
                break
            page += 1
        return found

    async def get_championship_standings(self, championship_id: str) -> dict:
        return await self._sm(f"/api/championship/{championship_id}/standings.json")

    async def list_championships(self) -> list:
        data = await self._sm("/api/championships")
        if isinstance(data, list):
            return data
        return data.get("championships", [])

    # ── AMS2 game server endpoints ─────────────────────────────────────────────

    async def fetch_track_names(self) -> dict[str, str]:
        """Fetch track list from the game server and cache id→name."""
        data = await self._gs("/api/list/tracks")
        tracks = data if isinstance(data, list) else data.get("list", [])
        mapping: dict[str, str] = {}
        for t in tracks:
            tid = str(t.get("id") or t.get("trackId") or "")
            name = t.get("name") or t.get("trackName") or ""
            if tid and name:
                mapping[tid] = name
        self._track_names = mapping
        return mapping

    def resolve_track(self, track_id: str) -> str:
        tid = str(track_id)
        return self._track_names.get(tid) or _STATIC_TRACK_NAMES.get(tid) or f"Track `{tid}`"

    async def session_status(self, members: bool = True, participants: bool = True) -> dict:
        params = {}
        if members:
            params["members"] = "true"
        if participants:
            params["participants"] = "true"
        return await self._gs("/api/session/status", params)
