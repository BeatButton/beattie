from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import aiohttp
from lxml import html

from ..postprocess import magick_gif_pp
from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


YT_SCRIPT_SELECTOR = ".//script[contains(text(),'responseContext')]"


class YTCommunity(Site):
    name = "yt_community"
    pattern = re.compile(
        r"https?://(?:www\.)?youtube\.com/"
        r"(?:post/|channel/[^/]+/community\?lb=)([\w-]+)",
    )

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, post_id: str):
        link = f"https://youtube.com/post/{post_id}"

        async with self.cog.get(link, use_browser_ua=True) as resp:
            root = html.document_fromstring(resp.content, self.cog.parser)

        if not (script := root.xpath(YT_SCRIPT_SELECTOR)):
            return

        data = json.loads(f"{{{script[0].text.partition('{')[-1].rpartition(';')[0]}")

        try:
            tab = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]
        except KeyError:
            queue.push_text(
                "This post is not visible in browser.",
                quote=False,
                force=True,
            )
            return
        section = tab["tabRenderer"]["content"]["sectionListRenderer"]["contents"][0]
        item = section["itemSectionRenderer"]["contents"][0]
        post = item["backstagePostThreadRenderer"]["post"]["backstagePostRenderer"]

        if not (attachment := post.get("backstageAttachment")):
            return

        images = attachment.get("postMultiImageRenderer", {}).get("images", [])

        if not images:
            images = [attachment]
        for image in images:
            if not (renderer := image.get("backstageImageRenderer")):
                continue

            thumbs = renderer["image"]["thumbnails"]
            img: str = max(thumbs, key=lambda t: t["width"])["url"]

            ext = None
            async with self.cog.get(
                img,
                headers={"Range": "bytes=30-33"},
                use_browser_ua=True,
            ) as resp:
                tag = resp.content
                if disp := resp.headers.get("Content-Disposition"):
                    _, params = aiohttp.multipart.parse_content_disposition(disp)
                    if name := params.get("filename"):
                        ext = name.rpartition(".")[2]

            pp = None
            ext = ext or "jpeg"

            if ext == "webp" and tag == b"ANIM":
                pp = magick_gif_pp
                ext = "gif"

            queue.push_file(img, filename=f"{post_id}.{ext}", postprocess=pp)

        if frags := post["contentText"].get("runs"):
            text = "".join(frag.get("text", "") for frag in frags)
            queue.push_text(text)
