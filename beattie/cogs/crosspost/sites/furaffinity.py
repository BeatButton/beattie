from __future__ import annotations

import re
from typing import TYPE_CHECKING

from lxml import html

from .selectors import OG_DESCRIPTION, OG_IMAGE, OG_TITLE
from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


AUTHOR_PATTERN = re.compile(r"furaffinity\.net/art/(\w+)/")


class FurAffinity(Site):
    name = "furaffinity"
    pattern = re.compile(
        r"https?://(?:www\.)?(?:[fv]?x)?f[ux]raffinity\.net/view/(\d+)"
    )

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, sub_id: str):
        link = f"https://www.fxraffinity.net/view/{sub_id}?full"
        async with self.cog.get(
            link, error_for_status=False, follow_redirects=False
        ) as resp:
            root = html.document_fromstring(resp.content, self.cog.parser)

        try:
            url = root.xpath(OG_IMAGE)[0].get("content")
        except IndexError:
            queue.push_text(
                "No images found. Post may be login-restricted.",
                quote=False,
                force=True,
            )
            return

        if m := AUTHOR_PATTERN.search(url):
            queue.author = m.group(1)

        queue.push_file(url)

        title = root.xpath(OG_TITLE)[0].get("content")
        desc = root.xpath(OG_DESCRIPTION)[0].get("content")
        queue.push_text(title, bold=True)
        queue.push_text(desc)
