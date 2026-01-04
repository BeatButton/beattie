from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, TypedDict

from discord import NotFound

from ..database_types import TextLength
from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class Image(TypedDict):
        originalUrl: str
        thumbnailUrl: str

    class File(TypedDict):
        name: str
        extension: str
        url: str

    class TextBlock(TypedDict):
        type: Literal["p"]
        text: str

    class ImageBlock(TypedDict):
        type: Literal["image"]
        imageId: str

    class FileBlock(TypedDict):
        type: Literal["file"]
        fileId: str

    Block = TextBlock | ImageBlock | FileBlock

    class Body(TypedDict):
        images: list[Image]
        files: list[File]
        blocks: list[Block]
        imageMap: dict[str, Image]
        fileMap: dict[str, File]

    class Post(TypedDict):
        creatorId: str
        title: str
        type: Literal["image", "file", "article"]
        body: Body | None

    class Response(TypedDict):
        body: Post


class Fanbox(Site):
    name = "fanbox"
    pattern = re.compile(
        r"https://(?:(?:www\.)?fanbox\.cc/@)?([\w-]+)(?:\.fanbox\.cc)?/posts/(\d+)",
    )

    async def on_invoke(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
    ):
        if not queue.handle_task.done():
            msg = await ctx.send("Solving challenge...")
            try:
                await queue.handle_task
            finally:
                try:
                    await msg.delete()
                except NotFound:
                    pass

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        user: str,
        post_id: str,
    ):
        queue.link = f"https://www.fanbox.cc/@{user}/posts/{post_id}"
        url = f"https://api.fanbox.cc/post.info?postId={post_id}"

        async with self.cog.flaresolverr() as fs:
            await fs.get("https://fanbox.cc")
            data: Response = await fs.get_json(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://www.fanbox.cc",
                },
            )

        post = data["body"]
        body = post["body"]
        if body is None:
            return

        queue.author = post["creatorId"]
        queue.push_text(post["title"], bold=True)
        headers = {"Referer": queue.link}

        match post["type"]:
            case "image":
                for image in body["images"]:
                    queue.push_fallback(
                        image["originalUrl"],
                        image["thumbnailUrl"],
                        headers=headers,
                    )
                if text := body.get("text", "").strip():
                    queue.push_text(
                        text,
                        interlaced=True,
                        length=TextLength.LONG,
                    )
            case "file":
                for file_info in body["files"]:
                    url = file_info["url"]
                    filename = file_info["name"] + "." + file_info["extension"]
                    queue.push_file(url, filename=filename)
                if text := body.get("text", "").strip():
                    queue.push_text(
                        text,
                        interlaced=True,
                        length=TextLength.LONG,
                    )
            case "article":
                blocks = body["blocks"]
                image_map = body["imageMap"]
                file_map = body["fileMap"]

                if not (image_map or file_map):
                    return

                for block in blocks:
                    match block["type"]:
                        case "p":
                            if text := block.get("text", "").strip():
                                queue.push_text(
                                    text,
                                    interlaced=True,
                                    length=TextLength.LONG,
                                )
                        case "image":
                            image = image_map[block["imageId"]]
                            queue.push_fallback(
                                image["originalUrl"],
                                image["thumbnailUrl"],
                                headers=headers,
                            )
                        case "file":
                            queue.push_file(file_map[block["fileId"]]["url"])
            case other:
                msg = f"Unrecognized post type {other}!"
                raise RuntimeError(msg)
