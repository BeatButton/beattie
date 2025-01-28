from __future__ import annotations

import re
from random import randint
from typing import TYPE_CHECKING

from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Nhentai(Site):
    name = "nhentai"
    pattern = re.compile(r"https?://(?:www\.)?nhentai\.net/g/(\d+)")
    concurrent = True

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, gal_id: str):
        api_url = f"https://nhentai.net/api/gallery/{gal_id}"
        async with self.cog.get(api_url) as resp:
            data = resp.json()

        media_id = data["media_id"]
        for i, page in enumerate(data["images"]["pages"], 1):
            match page["t"]:
                case "j":
                    ext = "jpg"
                case "p":
                    ext = "png"
                case "g":
                    ext = "gif"
                case "w":
                    ext = "webp"
                case oth:
                    raise RuntimeError(f"Unrecognized image type {oth}")
            x = randint(1, 4)
            queue.push_file(f"https://i{x}.nhentai.net/galleries/{media_id}/{i}.{ext}")

        queue.push_text(data["title"]["english"], bold=True)
