from __future__ import annotations

from base64 import b64encode
import re
from typing import TYPE_CHECKING

import toml

from beattie.utils.exceptions import ResponseError
from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Danbooru(Site):
    name = "danbooru"
    pattern = re.compile(r"https?://danbooru\.donmai\.us/posts/(\d+)")

    headers: dict[str, str]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)

        with open("config/crosspost/danbooru.toml") as fp:
            data = toml.load(fp)

        key = data["api_key"]
        user = data["user"]
        auth_slug = b64encode(f"{user}:{key}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth_slug}"}

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, post_id: str):
        api_url = f"https://danbooru.donmai.us/posts/{post_id}.json"
        async with self.cog.get(
            api_url, headers=self.headers, use_default_headers=False
        ) as resp:
            post = await resp.json()

        queue.author = post["tag_string_artist"]

        queue.link = f"https://danbooru.donmai.us/posts/{post_id}"

        queue.push_file(post["file_url"])

        async with self.cog.get(
            f"https://danbooru.donmai.us/posts/{post_id}/artist_commentary.json",
            headers=self.headers,
            use_default_headers=False,
        ) as resp:
            post_text = await resp.json()

        if title := post_text["original_title"]:
            queue.push_text(title, bold=True)

        if text := post_text["original_description"]:
            queue.push_text(text)

        if source := post["source"]:
            queue.push_text(source, quote=False, force=True)
