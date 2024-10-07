from __future__ import annotations

import re
from html import unescape as html_unescape
from typing import TYPE_CHECKING

from lxml import html

from .selectors import OG_DESCRIPTION, OG_IMAGE, OG_TITLE
from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Itaku(Site):
    name = "itaku"
    pattern = re.compile(r"https?://itaku\.ee/images/\d+")

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        async with self.cog.get(
            link,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; Discordbot/2.0; +https://discordapp.com)"
            },
        ) as resp:
            root = html.document_fromstring(await resp.read(), self.cog.parser)

        url = None
        if image := root.xpath(OG_IMAGE):
            url = image[0].get("content")

        if fullsize := root.xpath("//a[contains(@class, 'mat-raised-button')]"):
            url = fullsize[0].get("href") or url

        if url is None:
            return False

        queue.push_file(url)

        if title := html_unescape(root.xpath(OG_TITLE)[0].get("content")):
            title, _, author = title.rpartition(" - ")
            queue.author = author.split(" ")[1]
            queue.push_text(title, bold=True)
        if desc := html_unescape(root.xpath(OG_DESCRIPTION)[0].get("content")):
            queue.push_text(desc)
