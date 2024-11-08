from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .site import Site
from ..postprocess import ffmpeg_m3u8_to_mp4_pp

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


XRPC_FMT = (
    "https://bsky.social/xrpc/com.atproto.repo.getRecord"
    "?repo={}&collection=app.bsky.feed.post&rkey={}"
)


class Bluesky(Site):
    name = "bsky"
    pattern = re.compile(r"https?://(?:c|fx)?bsky\.app/profile/([^/]+)/post/(.+)")

    async def handler(
        self, ctx: CrosspostContext, queue: FragmentQueue, repo: str, rkey: str
    ):
        xrpc_url = XRPC_FMT.format(repo, rkey)
        async with self.cog.get(xrpc_url) as resp:
            data = await resp.json()

        post = data["value"]

        embed = post.get("embed", {})
        media = embed.get("media", embed)
        images = media.get("images", [])
        video = embed.get("video")

        if not (images or video):
            return False

        did = data["uri"].removeprefix("at://").partition("/")[0]

        queue.author = repo
        queue.link = f"https://bsky.app/profile/{repo}/post/{rkey}"

        if video:
            video_id = video["ref"]["$link"]
            url = f"https://video.bsky.app/watch/{did}/{video_id}/playlist.m3u8"
            filename = f"{video_id}.m3u8"
            queue.push_file(
                url,
                filename=filename,
                postprocess=ffmpeg_m3u8_to_mp4_pp,
                can_link=False,
            )

        for image in images:
            image = image["image"]
            image_id = image["ref"]["$link"]
            url = f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{image_id}@jpeg"
            filename = f"{image_id}.jpeg"
            queue.push_file(url, filename=filename)

        if text := post["text"]:
            queue.push_text(text)
