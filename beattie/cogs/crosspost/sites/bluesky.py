from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .site import Site
from ..postprocess import ffmpeg_m3u8_to_mp4_pp

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


POST_FMT = (
    "https://bsky.social/xrpc/com.atproto.repo.getRecord"
    "?repo={}&collection=app.bsky.feed.post&rkey={}"
)
PROFILE_FMT = "https://bsky.social/xrpc/com.atproto.repo.describeRepo?repo={}"


class Bluesky(Site):
    name = "bsky"
    pattern = re.compile(
        r"https?://(?:c|[fv]x)?[bx]skyx?\.app/profile/([^/]+)/post/([^/]+)"
    )

    async def handler(
        self, ctx: CrosspostContext, queue: FragmentQueue, repo: str, rkey: str
    ):
        xrpc_url = POST_FMT.format(repo, rkey)
        async with self.cog.get(xrpc_url) as resp:
            data = resp.json()

        post = data["value"]
        text: str | None = post["text"] or None

        try:
            embed = post.get("embed", {})
        except KeyError:
            return

        qtext: str | None = None
        qname: str | None = None
        if embed.get("$type") == "app.bsky.embed.record":
            _, _, did, _, qrkey = embed["record"]["uri"].split("/")
            xrpc_url = POST_FMT.format(did, qrkey)
            async with self.cog.get(xrpc_url) as resp:
                data = resp.json()

            post = data["value"]
            qtext = post["text"]
            embed = post.get("embed", {})

            async with self.cog.get(PROFILE_FMT.format(did)) as resp:
                pdata = resp.json()
            qname = pdata["handle"]

        media = embed.get("media", embed)
        images = media.get("images", [])
        video = media.get("video")

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

        match text, qtext:
            case None, None:
                pass
            case (txt, None) | (None, txt):
                queue.push_text(txt)
            case _:
                if qtext:
                    qtext = f" — *{qtext}*"
                queue.push_text(
                    f"\N{BRAILLE PATTERN BLANK}↳ @{qname}{qtext}", escape=False
                )
                queue.push_text(text)
