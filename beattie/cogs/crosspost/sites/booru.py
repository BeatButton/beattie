from __future__ import annotations

import urllib.parse as urlparse
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..cog import Crosspost

API_PARAMS = {"page": "dapi", "s": "post", "q": "index", "json": "1"}


async def get_booru_post(
    cog: Crosspost, link: str, api_url: str, params: dict[str, str]
) -> dict[str, Any] | None:
    parsed = urlparse.urlparse(link)
    query = urlparse.parse_qs(parsed.query)
    page = query.get("page")
    if page != ["post"]:
        return None
    id_ = query.get("id")
    if not id_:
        return None
    id_ = id_[0]
    params["id"] = id_
    async with cog.get(api_url, params=params) as resp:
        data = await resp.json()
    if not data:
        return None
    if isinstance(data, dict):
        data = data["post"]
    post = data[0]
    return post
