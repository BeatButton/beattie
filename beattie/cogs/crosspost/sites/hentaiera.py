from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from lxml import html

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

JSON_EXPR = re.compile(r"\$\.parseJSON\('([^']+)'\);")


class HentaiEra(Site):
    name = "hentaiera"
    pattern = re.compile(
        r"https?://(?:www\.)?"
        r"(?:imhentai\.xxx|(?:hentaienvy|hentaiera|hentaifox|hentairox|hentaizap)\.com)"
        r"/(?:gallery|view)/\d+",
    )
    concurrent = False

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        link: str,
    ):
        async with self.cog.get(link) as resp:
            root = html.document_fromstring(resp.content)

        base = root.xpath("//img[@data-src]")[0].get("data-src").rpartition("/")[0]
        script: str = root.xpath("//script[contains(text(), '$.parseJSON')]")[0].text
        data: dict[str, str] = json.loads(
            script.partition("$.parseJSON('")[2].partition("'")[0],
        )

        pages = [data[str(i)] for i in range(1, len(data) + 1)]

        for idx, page in enumerate(pages, 1):
            tag, *_ = page.split(",")
            match tag:
                case "j":
                    ext = "jpg"
                case "p":
                    ext = "png"
                case "g":
                    ext = "gif"
                case "w":
                    ext = "webp"
                case oth:
                    msg = f"Unrecognized image type {oth}"
                    raise RuntimeError(msg)

            queue.push_file(f"{base}/{idx}.{ext}")

        title = root.xpath("//title")[0].text.rpartition(" - ")[0]
        queue.push_text(title, bold=True)
