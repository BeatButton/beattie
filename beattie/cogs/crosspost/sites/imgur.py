from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypedDict

import toml

from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class Image(TypedDict):
        link: str

    class AlbumData(TypedDict):
        account_id: str
        link: str
        images: list[Image]

    class AlbumResponse(TypedDict):
        data: AlbumData

    class ImageData(TypedDict):
        account_id: str
        link: str

    class ImageResponse(TypedDict):
        data: ImageData


class Imgur(Site):
    name = "imgur"
    pattern = re.compile(
        r"https?://(?:www\.)?imgur\.com/(?:(a|gallery)/)?(?:(?:\w+)-)*(\w+)",
    )

    headers: dict[str, str]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        with open("config/crosspost/imgur.toml") as fp:
            data = toml.load(fp)

        client_id = data["id"]
        self.headers = {"Authorization": f"Client-ID {client_id}"}

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        fragment: str,
        album_id: str,
    ):
        is_album = bool(fragment)
        target = "album" if is_album else "image"

        async with self.cog.get(
            f"https://api.imgur.com/3/{target}/{album_id}",
            headers=self.headers,
        ) as resp:
            data: ImageResponse | AlbumResponse = resp.json()

        post = data["data"]

        if "images" in post:
            images = post["images"]
        else:
            images = [post]

        queue.author = str(post["account_id"])
        queue.link = f"https://imgur.com/a/{album_id}"

        for image in images:
            queue.push_file(image["link"])
