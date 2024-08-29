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
        r"https?://(?:www\.)(?:vx)?tiktok\.com/(?:@\w+/video/\d|t/\w+)+"
    )

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        if "vxtiktok.com" not in link:
            link = link.replace("tiktok.com", "vxtiktok.com")

        async with self.cog.get(
            link,
            allow_redirects=False,
            use_default_headers=False,
            headers={"User-Agent": "test"},
        ) as resp:
            root = html.document_fromstring(await resp.read(), self.cog.parser)

        try:
            url = root.xpath(OG_VIDEO)[0].get("content")
        except IndexError:
            queue.push_text("No video found.", force=True)
            return

        try:
            async with self.cog.get(
                url, method="HEAD", use_default_headers=False
            ) as resp:
                pass
        except ResponseError as e:
            queue.push_text(f"Proxy server returned error {e.code}.")
            return

        queue.push_file(url)

        desc = root.xpath(OG_DESCRIPTION)[0].get("content")
        queue.push_text(f">>> {desc}")
