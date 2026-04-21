import aiohttp
from typing import Optional


class AMS2Client:
    def __init__(self, base_url: str, server_id: int = 0):
        self.base_url = base_url.rstrip("/")
        self.server_id = server_id
        self._session: Optional[aiohttp.ClientSession] = None
        self._track_names: dict[str, str] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def _get(self, path: str, params: dict = None) -> dict | list:
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    def _server(self, path: str) -> str:
        """Prefix a path with the per-server proxy path."""
        return f"/server/{self.server_id}{path}"

    # ── Server Manager endpoints ───────────────────────────────────────────────

    async def healthcheck(self) -> dict:
        return await self._get("/healthcheck.json")

    async def list_results(self, page: int = 0, search: str = None) -> dict:
        """List results. Page is 0-indexed."""
        params = {"page": page}
        if search:
            params["q"] = search
        return await self._get("/api/results/list.json", params=params)

    async def get_result(self, url: str) -> dict:
        """Fetch a result file by its server_manager_results_json_url path."""
        path = url if url.startswith("/") else self._server(f"/result/download/{url}")
        return await self._get(path)

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
        return await self._get(f"/api/championship/{championship_id}/standings.json")

    async def list_championships(self) -> list:
        data = await self._get("/api/championships")
        if isinstance(data, list):
            return data
        return data.get("championships", [])

    # ── AMS2 game server endpoints (proxied via /server/{id}/) ────────────────

    async def fetch_track_names(self) -> dict[str, str]:
        """Fetch the track list and cache id→name. Returns the mapping."""
        data = await self._get(self._server("/api/list/tracks"))
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
        return self._track_names.get(str(track_id), f"Track `{track_id}`")

    async def session_status(self, members: bool = True, participants: bool = True) -> dict:
        params = {}
        if members:
            params["members"] = "true"
        if participants:
            params["participants"] = "true"
        return await self._get(self._server("/api/session/status"), params=params)
