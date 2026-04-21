import aiohttp
from typing import Optional


class AMS2Client:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

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
        path = url if url.startswith("/") else f"/server/0/result/download/{url}"
        return await self._get(path)

    async def list_race_results(self, count: int = 1) -> list[dict]:
        """
        Return up to `count` Race-session entries from the results listing,
        searching across pages as needed.
        """
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
