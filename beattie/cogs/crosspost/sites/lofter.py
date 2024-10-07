from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import html

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


LOFTER_IMG_SELECTOR = ".//a[contains(@class, 'imgclasstag')]/img"
LOFTER_TEXT_SELECTOR = (
    ".//div[contains(@class, 'content')]/div[contains(@class, 'text')]"
)


class Lofter(Site):
    name = "lofter"
    pattern = re.compile(r"https?://[\w-]+\.lofter\.com/post/\w+")

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        async with self.cog.get(link, use_default_headers=False) as resp:
            root = html.document_fromstring(await resp.read(), self.cog.parser)

        if elems := root.xpath(LOFTER_IMG_SELECTOR):
            img = elems[0]
        else:
            return False
        queue.push_file(img.get("src"))

        if elems := root.xpath(LOFTER_TEXT_SELECTOR):
            text = elems[0].text_content()
            queue.push_text(text)
