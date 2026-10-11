from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import html

from beattie.cogs.crosspost.database_types import TextLength
from beattie.utils.aioutils import aload
from beattie.utils.etc import translate_bbcode

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


SCRIPT_SELECTOR = "//script[contains(@src, 'submissionPageSetup.js')]"
AUTHOR_SELECTOR = "//div[@class='artist-name']/a"
TITLE_SELECTOR = "//div[@class='title']"
TEXT_SELECTOR = "//div[@id='saved-description']"
SINGLE_SELECTOR = "//div[@id='main-image']/a"
MULTI_SELECTOR = (
    "//div[contains(@class, 'other-images')]"
    "/div[contains(@class, 'submission-page-image-option-container')]/img"
)


class Mousepad(Site):
    name = "mousepad"
    pattern = re.compile(r"https?://mousepad\.art/s/\d+")
    headers: dict[str, str]

    async def load(self):
        self.headers = await aload("config/crosspost/mousepad.toml")

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        link: str,
    ):
        async with self.cog.get(link, headers=self.headers) as resp:
            root = html.document_fromstring(resp.content, self.cog.parser)

        queue.author = root.xpath(AUTHOR_SELECTOR)[0].text
        queue.link = link

        cdn = root.xpath(SCRIPT_SELECTOR)[0].get("data-content-server")

        if images := root.xpath(MULTI_SELECTOR):
            for image in images:
                name = image.get("name")
                src = f"{cdn}/images/full/{name}"
                queue.push_file(src)
        elif image := root.xpath(SINGLE_SELECTOR):
            queue.push_file(image[0].get("href"))
        else:
            return

        queue.push_text(root.xpath(TITLE_SELECTOR)[0].text.strip(), bold=True)
        if text := root.xpath(TEXT_SELECTOR)[0].text_content().strip():
            queue.push_text(
                translate_bbcode(text),
                length=TextLength.LONG,
            )
