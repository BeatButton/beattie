from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


XRPC_FMT = (
    "https://bsky.social/xrpc/com.atproto.repo.getRecord"
    "?repo={}&collection=app.bsky.feed.post&rkey={}"
)


class Bluesky(Site):
    name = "bsky"
    pattern = re.compile(r"https?://bsky\.app/profile/([^/]+)/post/(.+)")

    async def handler(
        self, ctx: CrosspostContext, queue: FragmentQueue, repo: str, rkey: str
    ):
        xrpc_url = XRPC_FMT.format(repo, rkey)
        async with self.cog.get(xrpc_url, use_default_headers=False) as resp:
            data = await resp.json()

        post = data["value"]

        if not (images := post.get("embed", {}).get("images")):
            return False

        did = data["uri"].removeprefix("at://").partition("/")[0]

        queue.link = f"https://bsky.app/profile/{repo}/post/{rkey}"

        for image in images:
            image = image["image"]
            image_id = image["ref"]["$link"]
            url = f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{image_id}@jpeg"
            filename = f"{image_id}.jpeg"
            queue.push_file(url, filename=filename)

        if text := post["text"]:
            queue.push_text(f">>> {text}")
