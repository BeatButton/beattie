from __future__ import annotations

import json
import re
from itertools import chain
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
        r"([\w-]+)(?:/|\.tumblr(?:\.com)?/post/)(\d+)",
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
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        blog: str,
        post_id: str,
    ):
        link = f"https://tumbex.com/{blog}.tumblr/post/{post_id}"

        async with self.cog.get(link, use_browser_ua=True) as resp:
            content = resp.content

        root = html.document_fromstring(content, self.cog.parser)

        if not (script := root.xpath(TUMBLR_SCRIPT_SELECTOR)):
            return

        data = json.loads(f"{{{script[0].text.partition('{')[-1].rpartition('}')[0]}}}")

        if (post_content := data["params"]["content"]) is None:
            queue.push_text(
                "Post inaccessible. It may require authentication.",
                force=True,
                quote=False,
            )
            return

        post = post_content["posts"][0]
        reblog_root = post["reblogRoot"]
        name = reblog_root["name"] if reblog_root else None
        blocks: list[Block]
        blocks = list(
            chain.from_iterable(
                iter(block["content"])
                for block in post["blocks"]
                if name is None or block["blog"]["name"] == name
            ),
        )

        if not any(map(self.embeddable, blocks)):
            return

        queue.link = f"https://{blog}.tumblr.com/post/{post_id}"
        queue.author = data["params"]["id"]

        for block in blocks:
            match block["type"]:
                case "text":
                    if text := block["text"].strip():
                        queue.push_text(text, interlaced=True)
                case "image":
                    url = block["hd"]
                    if url.endswith(".gifv"):
                        async with self.cog.get(
                            url,
                            headers={"Range": "bytes=0-2"},
                        ) as resp:
                            start = resp.content
                        if start.startswith(b"GIF"):
                            url = url[:-1]
                    queue.push_file(url)
                case "video":
                    if media := block.get("media"):
                        queue.push_file(media["url"])
