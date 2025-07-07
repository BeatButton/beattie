from __future__ import annotations

import re
from base64 import b64encode
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

    headers: dict[str, str]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)

        with open("config/crosspost/e621.toml") as fp:
            data = toml.load(fp)

        key = data["api_key"]
        user = data["user"]
        auth_slug = b64encode(f"{user}:{key}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth_slug}"}

    async def handler(self, _ctx: CrosspostContext, queue: FragmentQueue, post_id: str):
        params = {"tags": f"id:{post_id}"}
        api_url = "https://e621.net/posts.json"
        async with self.cog.get(api_url, params=params, headers=self.headers) as resp:
            data = resp.json()
        try:
            post = data["posts"][0]
        except IndexError:
            raise ResponseError(404, api_url)

        queue.author = " ".join(sorted(post["tags"]["artist"]))

        queue.link = f"https://e621.net/posts/{post_id}"

        queue.push_file(post["file"]["url"])

        if text := post.get("description"):
            queue.push_text(text)

        if sources := post.get("sources"):
            queue.push_text(sources[-1], quote=False, force=True)
