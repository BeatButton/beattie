from __future__ import annotations

import json
import urllib.parse
from typing import TYPE_CHECKING, Any, TypedDict

import httpx

if TYPE_CHECKING:
    from types import TracebackType

    class Config(TypedDict):
        solver: str
        proxy: str


class FlareSolverr:
    solver: str
    proxy: str
    session: str | None
    client: httpx.AsyncClient

    def __init__(self, solver: str, proxy: str):
        self.solver = solver
        self.proxy = proxy
        self.client = httpx.AsyncClient(follow_redirects=True, timeout=None)
        self.session = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ):
        await self.close()

    async def start(self):
        if self.session is None:
            data = await self._request(
                {"cmd": "sessions.create", "proxy": {"url": self.proxy}},
            )
            self.session = data["session"]

    async def close(self):
        if self.session is not None:
            await self._request({"cmd": "sessions.destroy", "session": self.session})
            self.session = None

    async def _request(self, command: dict[str, Any]) -> dict[str, Any]:
        resp = await self.client.post(
            self.solver,
            headers={"Content-Type": "application/json"},
            content=json.dumps(command),
        )
        data = resp.json()
        if data["status"] != "ok":
            msg = f"solver error: {data['message']}"
            raise RuntimeError(msg)

        return data

    async def get(self, url: str, *, headers: dict[str, str] = None) -> dict[str, Any]:
        if headers:
            for name, value in headers.items():
                slug = f"{name}:{value}"
                data = urllib.parse.quote(slug, safe="")
                url = f"{url}&$$headers[]={data}"
        return await self._request(
            {
                "cmd": "request.get",
                "url": url,
                "session": self.session,
            },
        )
