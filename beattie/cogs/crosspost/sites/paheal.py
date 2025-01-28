from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import html

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


IMG_SELECTOR = ".//img[@id='main_image']"
SOURCE_SELECTOR = ".//tr[@data-row='Source Link']/td//a"


class Paheal(Site):
    name = "paheal"
    pattern = re.compile(r"https?://rule34\.paheal\.net/post/view/(\d+)")

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, post: str):
        link = f"https://rule34.paheal.net/post/view/{post}"
        async with self.cog.get(link, use_browser_ua=True) as resp:
            root = html.document_fromstring(resp.content, self.cog.parser)

        img = root.xpath(IMG_SELECTOR)[0]
        url = img.get("src")
        mime = img.get("data-mime").partition("/")[2]
        filename = f"{post}.{mime}"
        queue.push_file(url, filename=filename)

        if source := root.xpath(SOURCE_SELECTOR):
            queue.push_text(source[0].get("href"), quote=False, force=True)
