from __future__ import annotations

import re
from itertools import cycle
from typing import TYPE_CHECKING, TypedDict

import toml

from .site import Site

if TYPE_CHECKING:
    from beattie.cogs.crosspost.cog import Crosspost

    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class Page(TypedDict):
        path: str

    class Title(TypedDict):
        pretty: str

    class Response(TypedDict):
        media_id: str
        title: Title
        pages: list[Page]

    class Cdn(TypedDict):
        image_servers: list[str]


API_FMT = "https://nhentai.net/api/v2/{}"


class Nhentai(Site):
    name = "nhentai"
    pattern = re.compile(r"https?://(?:www\.)?nhentai\.net/g/(\d+)")
    image_servers: list[str]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        with open("config/crosspost/nhentai.toml") as fp:
            data = toml.load(fp)

        key = data["api_key"]
        self.headers = {
            "Authorization": f"Key {key}",
            "Accept": "application/json",
        }

    async def load(self):
        async with self.cog.get(API_FMT.format("cdn")) as resp:
            data: Cdn = resp.json()
        self.image_servers = data["image_servers"]

    async def handler(self, _ctx: CrosspostContext, queue: FragmentQueue, gal_id: str):
        async with self.cog.get(API_FMT.format(f"galleries/{gal_id}")) as resp:
            data: Response = resp.json()

        servers = cycle(self.image_servers)
        for server, page in zip(servers, data["pages"], strict=False):
            queue.push_file(f"{server}/{page['path']}")

        queue.push_text(data["title"]["pretty"], bold=True)
