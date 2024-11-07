from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from discord import Embed

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Exhentai(Site):
    name = "exhentai"
    pattern = re.compile(r"https?://e[x-]hentai\.org/g/(\d+)/(\w+)")

    async def handler(
        self, ctx: CrosspostContext, queue: FragmentQueue, gal_id: str, token: str
    ):
        body = {"method": "gdata", "gidlist": [[int(gal_id), token]], "namespace": 1}

        api_url = "https://api.e-hentai.org/api.php"
        async with self.cog.get(
            api_url,
            method="POST",
            data=json.dumps(body),
            headers={"Content-Type": "application/json"},
        ) as resp:
            content = await resp.read()
            data = json.loads(content)

        data = data["gmetadata"][0]

        tag: str
        tags: dict[str, list[str]] = {}
        for tag in data["tags"]:
            namespace, _, tag = tag.partition(":")
            tags.setdefault(namespace, []).append(tag)

        taglist = "\n".join(f"{ns}: {', '.join(ts)}" for ns, ts in tags.items())

        embed = (
            Embed(title=data["title"], url=queue.link)
            .set_image(url=data["thumb"])
            .add_field(name="Category", value=data["category"])
            .add_field(name="Rating", value=data["rating"])
            .add_field(name="Uploader", value=data["uploader"])
            .add_field(name="Tags", value=taglist)
        )

        queue.push_embed(embed)
