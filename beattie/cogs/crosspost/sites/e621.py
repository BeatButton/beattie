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


class E621(Site):
    name = "e621"
    pattern = re.compile(r"https?://(?:www\.)?e621\.net/post(?:s|/show)/(\d+)")

    key: str
    user: str

    def __init__(self, cog: Crosspost):
        super().__init__(cog)

        with open("config/crosspost/e621.toml") as fp:
            data = toml.load(fp)

        if data:
            self.key = data["api_key"]
            self.user = data["user"]
        else:
            self.key = ""
            self.user = ""

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, post_id: str):
        params = {"tags": f"id:{post_id}"}
        if self.key:
            auth_slug = b64encode(f"{self.user}:{self.key}".encode()).decode()
            headers = {"Authorization": f"Basic {auth_slug}"}
        else:
            headers = {}
        api_url = "https://e621.net/posts.json"
        async with self.cog.get(
            api_url, params=params, headers=headers, use_default_headers=False
        ) as resp:
            data = await resp.json()
        try:
            post = data["posts"][0]
        except IndexError:
            raise ResponseError(404, api_url)

        queue.author = " ".join(sorted(post["tags"]["artist"]))

        queue.link = f"https://e621.net/posts/{post_id}"

        queue.push_file(post["file"]["url"])

        if text := post.get("description"):
            queue.push_text(f">>> {text}")

        if sources := post.get("sources"):
            queue.push_text(sources[-1], force=True)
