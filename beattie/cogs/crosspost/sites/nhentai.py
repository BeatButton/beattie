from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from discord import Embed

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Nhentai(Site):
    name = "nhentai"
    pattern = re.compile(r"https?://(?:www\.)?nhentai\.net/g/(\d+)")

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, gal_id: str):
        api_url = f"https://nhentai.net/api/gallery/{gal_id}"
        async with self.cog.get(
            api_url,
            use_default_headers=False,
        ) as resp:
            data = await resp.json()

        media_id = data["media_id"]
        for i, page in enumerate(data["images"]["pages"], 1):
            ext = ""
            page_t = page["t"]
            match page_t:
                case "j":
                    ext = "jpg"
                case "p":
                    ext = "png"

            if ext:
                queue.push_file(f"https://i.nhentai.net/galleries/{media_id}/{i}.{ext}")
            else:
                queue.push_text(f"Unrecognized image type {page_t}", force=True)

        queue.push_text(data["title"]["english"])
