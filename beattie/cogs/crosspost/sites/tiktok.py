from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import html

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Tiktok(Site):
    name = "tiktok"
    pattern = re.compile(
        r"(https?://(?:www\.)(?:vx)?tiktok\.com/(?:@[\w\.]+/video/|t/)(\w+))",
    )

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        link: str,
        video_id: str,
    ):
        async with self.cog.get(f"https://kktiktok.com/t/{video_id}?_kk=1") as resp:
            url = resp.json()["url"]

        filename = f"{video_id}.mp4"

        queue.push_file(url, filename=filename)

        async with self.cog.get(link, use_browser_ua=True) as resp:
            root = html.document_fromstring(resp.content, self.cog.parser)

        text: str = root.find(".//title").text
        queue.push_text(text.removeprefix("TikTok - "))
