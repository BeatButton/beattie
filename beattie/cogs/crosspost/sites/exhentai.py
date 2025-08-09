from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, TypedDict

from discord import Embed

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class GalleryMetadata(TypedDict):
        title: str
        category: str
        thumb: str
        uploader: str
        rating: str
        tags: list[str]

    class Response(TypedDict):
        gmetadata: list[GalleryMetadata]


class Exhentai(Site):
    name = "exhentai"
    pattern = re.compile(r"https?://e[x-]hentai\.org/g/(\d+)/(\w+)")

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        gal_id: str,
        token: str,
    ):
        body = {"method": "gdata", "gidlist": [[int(gal_id), token]], "namespace": 1}

        api_url = "https://api.e-hentai.org/api.php"
        async with self.cog.get(
            api_url,
            method="POST",
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
        ) as resp:
            data: Response = resp.json()

        gal = data["gmetadata"][0]

        tag: str
        tags: dict[str, list[str]] = {}
        for tag in gal["tags"]:
            namespace, _, tag = tag.partition(":")
            tags.setdefault(namespace, []).append(tag)

        taglist = "\n".join(f"{ns}: {', '.join(ts)}" for ns, ts in tags.items())

        embed = (
            Embed(title=gal["title"], url=queue.link)
            .set_image(url=gal["thumb"])
            .add_field(name="Category", value=gal["category"])
            .add_field(name="Rating", value=gal["rating"])
            .add_field(name="Uploader", value=gal["uploader"])
            .add_field(name="Tags", value=taglist)
        )

        queue.push_embed(embed)
