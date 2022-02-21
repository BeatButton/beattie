from types import TracebackType
from typing import Any

from aiohttp import ClientResponse, ClientSession, ServerDisconnectedError

from .exceptions import ResponseError


class get:
    """Returns a response to a URL."""

    def __init__(
        self, session: ClientSession, url: str, *, method: str = "GET", **kwargs: Any
    ):
        self.session = session
        self.url = url
        headers = kwargs.get("headers", {})
        if "Accept-Encoding" not in headers:
            headers["Accept-Encoding"] = "gzip, deflate, sdch"
        if "user-agent" not in headers:
            headers["user-agent"] = "BeattieBot/1.0 (BeatButton)"
        kwargs["headers"] = headers
        if "timeout" not in kwargs:
            kwargs["timeout"] = None
        self.kwargs = kwargs
        self.method = method

    async def __aenter__(self) -> ClientResponse:
        try:
            self.resp = await self.session.request(self.method, self.url, **self.kwargs)
        except ServerDisconnectedError:
            return await self.__aenter__()
        except OSError as e:
            if e.errno == 104:
                return await self.__aenter__()
            else:
                raise e from None
        if self.resp.status != 200:
            self.resp.close()
            raise ResponseError(code=self.resp.status, url=str(self.resp.url))
        return self.resp

    async def __aexit__(
        self, exc_type: type, exc: Exception, tb: TracebackType
    ) -> None:
        self.resp.close()
