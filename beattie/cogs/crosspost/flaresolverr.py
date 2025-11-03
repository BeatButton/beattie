from __future__ import annotations

import json
import urllib.parse
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

import httpx
from lxml import html

if TYPE_CHECKING:
    from types import TracebackType

    from beattie.cogs.crosspost.cog import Crosspost

    class Config(TypedDict):
        solver: str
        proxy: str

    class Proxy(TypedDict):
        url: str

    class SessionsCreateCmd(TypedDict):
        cmd: Literal["sessions.create"]
        session: NotRequired[str]
        proxy: NotRequired[Proxy]

    class SessionsDestroyCmd(TypedDict):
        cmd: Literal["sessions.destroy"]
        session: str

    class RequestGetBasicCmd(TypedDict):
        cmd: Literal["request.get"]
        url: str

    class RequestGetSessionCmd(TypedDict):
        cmd: Literal["request.get"]
        url: str
        session: str

    class RequestGetProxyCmd(TypedDict):
        cmd: Literal["request.get"]
        url: str
        proxy: Proxy

    RequestGetCmd = RequestGetBasicCmd | RequestGetSessionCmd | RequestGetProxyCmd

    Command = SessionsCreateCmd | SessionsDestroyCmd | RequestGetCmd

    class Response(TypedDict):
        status: str
        message: str

    class SessionsCreate(Response):
        session: str

    class Solution(TypedDict):
        response: str

    class RequestsGet(Response):
        status: str
        message: str
        solution: Solution


class FlareSolverr:
    cog: Crosspost
    solver: str
    proxy: str
    session: str | None
    client: httpx.AsyncClient

    def __init__(self, cog: Crosspost, solver: str, proxy: str):
        self.cog = cog
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
            data: SessionsCreate = await self._request(
                {
                    "cmd": "sessions.create",
                    "proxy": {"url": self.proxy},
                },
            )
            self.session = data["session"]

    async def close(self):
        if self.session is not None:
            await self._request({"cmd": "sessions.destroy", "session": self.session})
            self.session = None

    async def _request(self, command: Command) -> Any:
        resp = await self.client.post(
            self.solver,
            headers={"Content-Type": "application/json"},
            content=json.dumps(command),
        )
        data: Response = resp.json()
        if data["status"] != "ok":
            msg = f"solver error: {data['message']}"
            raise RuntimeError(msg)

        return data

    async def get(self, url: str, *, headers: dict[str, str] = None) -> RequestsGet:
        if headers:
            for name, value in headers.items():
                slug = f"{name}:{value}"
                data = urllib.parse.quote(slug, safe="")
                url = f"{url}&$$headers[]={data}"
        if self.session is None:
            msg = "get called before session was set"
            raise RuntimeError(msg)
        return await self._request(
            {
                "cmd": "request.get",
                "url": url,
                "session": self.session,
            },
        )

    async def get_json(self, url: str, *, headers: dict[str, str] = None) -> Any:
        resp = await self.get(url, headers=headers)
        root = html.document_fromstring(resp["solution"]["response"], self.cog.parser)
        return json.loads(root.xpath("//pre")[0].text)
