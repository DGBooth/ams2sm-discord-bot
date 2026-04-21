import aiohttp
import os
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

    async def list_results(self, page: int = 1, search: str = None) -> dict:
        params = {"page": page}
        if search:
            params["q"] = search
        return await self._get("/api/results/list.json", params=params)

    async def get_result(self, url: str) -> dict:
        # Accept either a full path or bare filename
        if url.startswith("/") or url.startswith("http"):
            path = url if url.startswith("/") else url.split(self.base_url, 1)[-1]
        else:
            path = f"/api/results/{url}"
        return await self._get(path)

    def _result_url(self, entry: dict) -> Optional[str]:
        return (
            entry.get("results_json_url")
            or entry.get("url")
            or entry.get("ResultFile")
            or entry.get("File")
        )

    async def get_latest_result(self) -> Optional[dict]:
        listing = await self.list_results(page=1)
        results = listing.get("results", [])
        if not results:
            return None
        first = results[0]
        url = self._result_url(first)
        if not url:
            return None
        data = await self.get_result(url)
        data["_meta"] = first
        return data

    async def get_championship_standings(self, championship_id: str) -> dict:
        return await self._get(f"/api/championship/{championship_id}/standings.json")

    async def list_championships(self) -> list:
        data = await self._get("/api/championships")
        if isinstance(data, list):
            return data
        return data.get("championships", [])
