from __future__ import annotations

import ssl

import certifi
import httpx


def make_session(*, verify: bool | None = None) -> httpx.AsyncClient:
    if verify is None:
        ctx = ssl.create_default_context(cafile=certifi.where())
    else:
        ctx = verify
    transport = httpx.AsyncHTTPTransport(verify=ctx)
    return httpx.AsyncClient(
        follow_redirects=True,
        timeout=None,
        transport=transport,
        verify=ctx,
    )
