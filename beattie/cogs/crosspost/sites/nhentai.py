from __future__ import annotations

import re
from random import randint
from typing import TYPE_CHECKING, Literal, TypedDict

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class Page(TypedDict):
        t: Literal["j", "p", "g", "w"]

    class Images(TypedDict):
        pages: list[Page]

    class Title(TypedDict):
        english: str

    class Response(TypedDict):
        media_id: str
        title: Title
        images: Images


class Nhentai(Site):
    name = "nhentai"
    pattern = re.compile(r"https?://(?:www\.)?nhentai\.net/g/(\d+)")
    concurrent = True

    async def handler(self, _ctx: CrosspostContext, queue: FragmentQueue, gal_id: str):
        api_url = f"https://nhentai.net/api/gallery/{gal_id}"
        async with self.cog.get(api_url) as resp:
            data: Response = resp.json()

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
                    msg = f"Unrecognized image type {oth}"
                    raise RuntimeError(msg)
            x = randint(1, 4)
            queue.push_file(f"https://i{x}.nhentai.net/galleries/{media_id}/{i}.{ext}")

        queue.push_text(data["title"]["english"], bold=True)
