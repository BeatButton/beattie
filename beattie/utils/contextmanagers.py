import copy
import logging
from types import TracebackType
from typing import Any, AsyncContextManager, Generic, Mapping, TypeVar

from niquests import AsyncSession, AsyncResponse

from .exceptions import ResponseError

LOGGER = logging.getLogger(__name__)


class get:
    """Returns a response to the first URL that returns a 200 status code."""

    session: AsyncSession
    resp: AsyncResponse
    urls: tuple[str, ...]
    index: int
    method: str
    error_for_status: bool
    kwargs: Mapping[str, Any]

    def __init__(
        self,
        session: AsyncSession,
        *urls: str,
        method: str = "GET",
        error_for_status: bool = True,
        **kwargs: Any,
    ):
        self.session = session
        self.urls = urls
        self.index = 0
        headers = copy.copy(kwargs.get("headers", {}))
        if "Accept-Encoding" not in headers:
            headers["Accept-Encoding"] = "gzip, deflate, sdch, br"
        if "User-Agent" not in headers:
            headers["User-Agent"] = "BeattieBot/1.0 (BeatButton)"
        kwargs["headers"] = headers
        if "timeout" not in kwargs:
            kwargs["timeout"] = None
        self.kwargs = kwargs
        self.method = method
        self.error_for_status = error_for_status

    async def __aenter__(self) -> AsyncResponse:
        while True:
            try:
                resp = await self._aenter_inner()
            except ResponseError:
                self.index += 1
                if self.index >= len(self.urls):
                    raise
            else:
                return resp

    async def _aenter_inner(self) -> AsyncResponse:
        url = self.urls[self.index]
        LOGGER.debug(f"making a {self.method} request to {url}")

        self.resp = await self.session.request(
            self.method, url, stream=True, **self.kwargs
        )

        if self.error_for_status and self.resp.status_code not in range(200, 300):
            await self.resp.close()
            raise ResponseError(code=self.resp.status_code, url=str(self.resp.url))
        return self.resp

    async def __aexit__(self, exc_type: type, exc: Exception, tb: TracebackType):
        await self.resp.close()


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
