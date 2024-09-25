from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from ..postprocess import ffmpeg_gif_pp
from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

URL_GROUPS = re.compile(r"https?://(misskey\.\w+)/notes/(\w+)")


class Misskey(Site):
    name = "misskey"
    pattern = re.compile(r"https?://misskey\.\w+/notes/\w+")

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        if (match := URL_GROUPS.match(link)) is None:
            return False
        site, post = match.groups()

        url = f"https://{site}/api/notes/show"
        body = json.dumps({"noteId": post}).encode("utf-8")

        async with self.cog.get(
            url,
            method="POST",
            data=body,
            use_default_headers=False,
            headers={"Content-Type": "application/json"},
        ) as resp:
            data = await resp.json()

        if not (files := data["files"]):
            return False

        queue.author = data["user"]["id"]

        for file in files:
            url = file["url"]
            pp = None
            ext = url.rpartition("/")[-1].rpartition("?")[0].rpartition(".")[-1]
            if ext == "apng":
                pp = ffmpeg_gif_pp

            queue.push_file(url, postprocess=pp)

        if text := data["text"]:
            queue.push_text(f">>> {text}")
