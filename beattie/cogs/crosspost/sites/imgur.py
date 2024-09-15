from __future__ import annotations

import re
from typing import TYPE_CHECKING

import toml

from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Imgur(Site):
    name = "imgur"
    pattern = re.compile(r"https?://(?:www\.)?imgur\.com/(a|gallery/)?(\w+)")

    headers: dict[str, str] = {}

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        with open("config/crosspost/imgur.toml") as fp:
            data = toml.load(fp)

        client_id = data["id"]
        self.headers["Authorization"] = f"Client-ID {client_id}"

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        fragment: str | None,
        album_id: str,
    ):
        is_album = bool(fragment)
        target = "album" if is_album else "image"

        async with self.cog.get(
            f"https://api.imgur.com/3/{target}/{album_id}",
            use_default_headers=False,
            headers=self.headers,
        ) as resp:
            data = (await resp.json())["data"]

        if is_album:
            images = data["images"]
        else:
            images = [data]

        queue.author = str(data["account_id"])
        queue.link = f"https://imgur.com/a/{album_id}"

        for image in images:
            queue.push_file(image["link"])
