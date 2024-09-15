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


AUTHOR_SELECTOR = "//div[contains(@class, 'username')]"


class Pillowfort(Site):
    name = "pillowfort"
    pattern = re.compile(r"https?://(?:www\.)?pillowfort\.social/posts/\d+")

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        async with self.cog.get(link) as resp:
            root = html.document_fromstring(await resp.read(), self.cog.parser)

        if not (images := root.xpath(OG_IMAGE)):
            return False

        queue.author = root.xpath(AUTHOR_SELECTOR)[0].text_content().strip()

        images.reverse()

        headers = {"Referer": link}
        for image in images:
            url = image.get("content").replace("_small.png", ".png")
            queue.push_file(url, headers=headers)

        if title := html_unescape(root.xpath(OG_TITLE)[0].get("content")):
            queue.push_text(f"**{title}**")
        if desc := html_unescape(root.xpath(OG_DESCRIPTION)[0].get("content")):
            queue.push_text(f">>> {desc}")
