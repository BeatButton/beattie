from __future__ import annotations

import copy
import logging
from contextlib import AbstractAsyncContextManager
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from .exceptions import ResponseError

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

    from httpx import AsyncClient, Response

LOGGER = logging.getLogger(__name__)


class get:
    """Returns a response to the first URL that returns a 200 status code."""

    session: AsyncClient
    resp: Response
    urls: tuple[str, ...]
    index: int
    method: str
    error_for_status: bool
    kwargs: Mapping[str, Any]

    def __init__(
        self,
        session: AsyncClient,
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

    async def __aenter__(self) -> Response:
        while True:
            try:
                resp = await self._aenter_inner()
            except ResponseError:  # noqa: PERF203
                self.index += 1
                if self.index >= len(self.urls):
                    raise
            else:
                return resp

    async def _aenter_inner(self) -> Response:
        url = self.urls[self.index]
        LOGGER.debug("making a %s request to %s", self.method, url)

        self.resp = await self.session.request(self.method, url, **self.kwargs)

        if self.error_for_status and self.resp.status_code not in range(200, 300):
            await self.resp.aclose()
            raise ResponseError(code=self.resp.status_code, url=str(self.resp.url))
        return self.resp

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ):
        pass


CM = TypeVar("CM", bound=AbstractAsyncContextManager)


class MultiAsyncWith(Generic[CM]):
    def __init__(self, ctxs: list[CM]):
        self.ctxs = ctxs

    async def __aenter__(self) -> list[CM]:
        for ctx in self.ctxs:
            await ctx.__aenter__()
        return self.ctxs

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ):
        for ctx in self.ctxs:
            await ctx.__aexit__(exc_type, exc, tb)
