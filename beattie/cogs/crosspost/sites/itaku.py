from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Itaku(Site):
    name = "itaku"
    pattern = re.compile(r"https?://itaku\.ee/images/(\d+)")

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        image_id: str,
    ):
        async with self.cog.get(
            f"https://itaku.ee/api/galleries/images/{image_id}",
            headers={
                "Accept": "application/json",
            },
        ) as resp:
            post = resp.json()

        url = post.get("image_xl")

        if url is None:
            url = post.get("image")

        if url is None:
            return

        queue.author = post["owner_username"]
        queue.push_file(url)

        if title := post.get("title"):
            queue.push_text(title, bold=True)
        if desc := post.get("description"):
            queue.push_text(desc)
