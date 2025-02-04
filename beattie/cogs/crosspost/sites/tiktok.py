from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import html

from beattie.utils.exceptions import ResponseError
from .selectors import OG_DESCRIPTION, OG_VIDEO
from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Tiktok(Site):
    name = "tiktok"
    pattern = re.compile(
        r"https?://(?:www\.)(?:vx)?tiktok\.com/(?:@[\w\.]+/video/\d+|t/\w+)+"
    )

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        if "vxtiktok.com" not in link:
            link = link.replace("tiktok.com", "vxtiktok.com")

        try:
            async with self.cog.get(
                link,
                follow_redirects=False,
                headers={"User-Agent": "test"},
            ) as resp:
                root = html.document_fromstring(resp.content, self.cog.parser)
        except ResponseError:
            raise

        try:
            url = root.xpath(OG_VIDEO)[0].get("content")
        except IndexError:
            raise RuntimeError("no video in vxtiktok response") from None

        try:
            async with self.cog.get(url, method="HEAD") as resp:
                pass
        except ResponseError:
            raise

        video_id = url.rpartition("/")[2]
        filename = f"{video_id}.mp4"

        queue.push_file(url, filename=filename)

        desc = root.xpath(OG_DESCRIPTION)[0].get("content")
        queue.push_text(desc)
