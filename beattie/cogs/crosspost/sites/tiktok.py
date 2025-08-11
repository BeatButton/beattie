from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypedDict

from beattie.utils.exceptions import ResponseError

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class Response(TypedDict):
        url: str


class Tiktok(Site):
    name = "tiktok"
    pattern = re.compile(
        r"https?://(?:\w+\.)?(?:vx|kk)?tiktok\.com/(?:@[\w\.]+/video/|t/)?([\w\-]+)",
    )

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        video_id: str,
    ):
        link = f"https://kktiktok.com/t/{video_id}?_kk=1"
        async with self.cog.get(link) as resp:
            post: Response = resp.json()

        url = post["url"]

        if url is None:
            raise ResponseError(404, link)

        filename = f"{video_id}.mp4"

        queue.push_file(url, filename=filename)
