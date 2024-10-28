from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, NotRequired, TypedDict

from lxml import html

from .site import Site

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


TUMBLR_SCRIPT_SELECTOR = ".//script[contains(text(),'window.launcher')]"


class Block(TypedDict):
    type: str
    text: str
    hd: str
    media: NotRequired[dict[str, str]]


class Tumblr(Site):
    name = "tumblr"
    pattern = re.compile(
        r"https?://(?:(?:www\.)?tumb(?:lr|ex)\.com/)?"
        r"([\w-]+)(?:/|\.tumblr(?:\.com)?/post/)(\d+)"
    )

    @staticmethod
    def embeddable(block: Block) -> bool:
        match block["type"]:
            case "image":
                return True
            case "video":
                return "media" in block
            case _:
                return False

    async def handler(
        self, ctx: CrosspostContext, queue: FragmentQueue, blog: str, post: str
    ):
        link = f"https://tumbex.com/{blog}.tumblr/post/{post}"

        async with self.cog.get(link) as resp:
            content = await resp.read()

        root = html.document_fromstring(content, self.cog.parser)

        if not (script := root.xpath(TUMBLR_SCRIPT_SELECTOR)):
            return False

        data = json.loads(f"{{{script[0].text.partition('{')[-1].rpartition('}')[0]}}}")

        if (post_content := data["params"]["content"]) is None:
            queue.push_text(
                "Post inaccessible. It may require authentication.",
                force=True,
                quote=False,
            )
            return False

        blocks: list[Block]
        blocks = post_content["posts"][0]["blocks"][0]["content"]

        if not any(map(self.embeddable, blocks)):
            return False

        queue.link = f"https://{blog}.tumblr.com/post/{post}"
        queue.author = data["params"]["id"]

        for block in blocks:
            match block["type"]:
                case "text":
                    if text := block["text"].strip().replace("\n", "\n> "):
                        queue.push_text(f"> {text}", interlaced=True)
                case "image":
                    url = block["hd"]
                    if url.endswith(".gifv"):
                        async with self.cog.get(
                            url, headers={"Range": "bytes=0-2"}
                        ) as resp:
                            start = await resp.read()
                        if start.startswith(b"GIF"):
                            url = url[:-1]
                    queue.push_file(url)
                case "video":
                    if media := block.get("media"):
                        queue.push_file(media["url"])
