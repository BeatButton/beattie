from __future__ import annotations

import re
from typing import TYPE_CHECKING, NotRequired, TypedDict

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class Response(TypedDict):
        owner_username: str
        image_xl: NotRequired[str]
        image: str
        title: str
        description: str


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
            post: Response = resp.json()

        url = post.get("image_xl")

        if url is None:
            url = post["image"]

        queue.author = post["owner_username"]
        queue.push_file(url)

        if title := post.get("title"):
            queue.push_text(title, bold=True)
        if desc := post.get("description"):
            queue.push_text(desc)
