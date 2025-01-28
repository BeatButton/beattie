from __future__ import annotations

import re
from typing import TYPE_CHECKING

import toml
from lxml import html


from beattie.utils.etc import translate_markdown
from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

FULLSIZE_EXPR = re.compile(r"""popup\((['"])(?P<link>[^\1]*?)\1""")
IMG_SELECTOR = "//img[@id='idPreviewImage']"
TEXT_SELECTOR = "//div[@id='artist-comment']//div[contains(@class, 'commentData')]"
AUTHOR_SELECTOR = "//div[contains(@class, 'subheader')]/span/a"


class YGallery(Site):
    name = "ygal"
    pattern = re.compile(r"https?://(?:(?:old|www)\.)?y-gallery\.net/view/(\d+)")

    headers: dict[str, str] = {}

    def __init__(self, cog: Crosspost):
        super().__init__(cog)

        with open("config/crosspost/ygal.toml") as fp:
            self.headers = toml.load(fp)

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, gal_id: str):

        link = f"https://old.y-gallery.net/view/{gal_id}/"

        async with self.cog.get(
            link,
            headers=self.headers,
            use_browser_ua=True,
        ) as resp:
            root = html.document_fromstring(resp.content, self.cog.parser)

        queue.author = root.xpath(AUTHOR_SELECTOR)[0].text_content().strip()

        img = root.xpath(IMG_SELECTOR)[0]
        m = FULLSIZE_EXPR.match(img.get("onclick"))
        assert m is not None
        link = m["link"]
        queue.push_file(link, headers={"Referer": link})

        comment = html.tostring(root.xpath(TEXT_SELECTOR)[0], encoding=str)
        assert isinstance(comment, str)
        if title := img.get("alt"):
            queue.push_text(title, bold=True)
        comment = comment.strip()
        comment = comment.removeprefix('<div class="commentData">')
        comment = comment.removesuffix("</div>")
        comment = re.sub(r" ?<img[^>]*> ?", "", comment)
        if comment := translate_markdown(comment).strip():
            queue.push_text(comment)
