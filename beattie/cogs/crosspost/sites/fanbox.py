from __future__ import annotations

import re
from typing import TYPE_CHECKING

import aiohttp

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Fanbox(Site):
    name = "fanbox"
    pattern = re.compile(
        r"https://(?:(?:www\.)?fanbox\.cc/@)?([\w-]+)(?:\.fanbox\.cc)?/posts/(\d+)"
    )

    headers: dict[str, str] = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.fanbox.cc",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    }

    async def handler(
        self, ctx: CrosspostContext, queue: FragmentQueue, user: str, post_id: str
    ):
        queue.link = f"https://www.fanbox.cc/@{user}/posts/{post_id}"
        url = f"https://api.fanbox.cc/post.info?postId={post_id}"
        headers = {**self.headers, "Referer": queue.link}
        async with (
            aiohttp.ClientSession() as sess,
            self.cog.get(url, headers=headers, session=sess) as resp,
        ):
            data = await resp.json()

        post = data["body"]
        body = post["body"]
        if body is None:
            return False

        queue.author = post["creatorId"]

        match post["type"]:
            case "image":
                for image in body["images"]:
                    queue.push_fallback(
                        image["originalUrl"], image["thumbnailUrl"], headers
                    )
                if text := body.get("text", "").strip():
                    queue.push_text(f">>> {text}", interlaced=True)
            case "file":
                for file_info in body["files"]:
                    url = file_info["url"]
                    filename = file_info["name"] + "." + file_info["extension"]
                    queue.push_file(url, filename=filename)
                if text := body.get("text", "").strip():
                    queue.push_text(f">>> {text}", interlaced=True)
            case "article":
                blocks = body["blocks"]
                image_map = body["imageMap"]
                file_map = body["fileMap"]

                if not (image_map or file_map):
                    return False

                for block in blocks:
                    match block["type"]:
                        case "p":
                            if text := block.get("text", "").strip():
                                queue.push_text(f"> {text}", interlaced=True)
                        case "image":
                            image = image_map[block["imageId"]]
                            queue.push_fallback(
                                image["originalUrl"],
                                image["thumbnailUrl"],
                                headers,
                            )
                        case "file":
                            queue.push_file(file_map[block["fileId"]]["url"])
            case other:
                queue.push_text(
                    f"Unrecognized post type {other}! This is a bug.", force=True
                )
                return False
