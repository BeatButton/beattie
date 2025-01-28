from __future__ import annotations

import re
from typing import TYPE_CHECKING

import toml
from html import unescape as html_unescape
from lxml import etree

from beattie.utils.etc import translate_markdown

from .site import Site
from .booru import API_PARAMS, get_booru_post

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


GELBOORU_API_URL = "https://gelbooru.com/index.php"


class Gelbooru(Site):
    name = "gelbooru"
    pattern = re.compile(r"https?://gelbooru\.com/index\.php\?(?:\w+=[^>&\s]+&?){2,}")

    gelbooru_params: dict[str, str]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        with open("config/crosspost/gelbooru.toml") as fp:
            self.gelbooru_params = toml.load(fp)

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        params = {**API_PARAMS, **self.gelbooru_params}
        post = await get_booru_post(self.cog, link, GELBOORU_API_URL, params)
        if post is None:
            return False

        tag_params = {
            **API_PARAMS,
            **self.gelbooru_params,
            "s": "tag",
            "names": post["tags"],
        }
        async with self.cog.get(GELBOORU_API_URL, params=tag_params) as resp:
            tags = resp.json()["tag"]

        queue.author = " ".join(sorted(tag["name"] for tag in tags if tag["type"] == 1))

        queue.push_file(post["file_url"])

        params["s"] = "note"
        del params["json"]
        params["post_id"] = params.pop("id")
        async with self.cog.get(GELBOORU_API_URL, params=params) as resp:
            root = etree.fromstring(resp.content, self.cog.xml_parser)

        notes = list(root)
        if notes:
            notes.sort(key=lambda n: int(n.get("y")))
            text = "\n".join(f'"{n.get("body")}"' for n in notes)
            text = translate_markdown(text)
            queue.push_text(text)

        if source := post.get("source"):
            queue.push_text(html_unescape(source), quote=False, force=True)
