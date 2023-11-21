from types import TracebackType
from typing import Any, AsyncContextManager, Generic, TypeVar

from aiohttp import ClientResponse, ClientSession, ServerDisconnectedError

from .exceptions import ResponseError


class get:
    """Returns a response to the first URL that returns a 200 status code."""

    def __init__(
        self, session: ClientSession, *urls: str, method: str = "GET", **kwargs: Any
    ):
        self.session = session
        self.urls = urls
        self.index = 0
        headers = kwargs.get("headers", {})
        if "Accept-Encoding" not in headers:
            headers["Accept-Encoding"] = "gzip, deflate, sdch"
        if "User-Agent" not in headers:
            headers["User-Agent"] = "BeattieBot/1.0 (BeatButton)"
        kwargs["headers"] = headers
        if "timeout" not in kwargs:
            kwargs["timeout"] = None
        self.kwargs = kwargs
        self.method = method

    async def __aenter__(self) -> ClientResponse:
        while True:
            try:
                resp = await self._aenter_inner()
            except ResponseError as e:
                self.index += 1
                if self.index >= len(self.urls):
                    raise e from None
            else:
                return resp

    async def _aenter_inner(self) -> ClientResponse:
        try:
            self.resp = await self.session.request(
                self.method, self.urls[self.index], **self.kwargs
            )
        except ServerDisconnectedError:
            return await self.__aenter__()
        except OSError as e:
            if e.errno == 104:
                return await self.__aenter__()
            else:
                raise e from None
        if self.resp.status not in range(200, 300):
            self.resp.close()
            raise ResponseError(code=self.resp.status, url=str(self.resp.url))
        return self.resp

    async def __aexit__(self, exc_type: type, exc: Exception, tb: TracebackType):
        self.resp.close()


CM = TypeVar("CM", bound=AsyncContextManager)


class MultiAsyncWith(Generic[CM]):
    def __init__(self, ctxs: list[CM]):
        self.ctxs = ctxs

    async def __aenter__(self) -> list[CM]:
        for ctx in self.ctxs:
            await ctx.__aenter__()
        return self.ctxs

    async def __aexit__(self, exc_type: type, exc: Exception, tb: TracebackType):
        for ctx in self.ctxs:
            await ctx.__aexit__(exc_type, exc, tb)
