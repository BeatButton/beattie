from __future__ import annotations

import re
from typing import TYPE_CHECKING

import toml

from beattie.utils.etc import translate_bbcode

from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


API_FMT = "https://inkbunny.net/api_{}.php"


class Inkbunny(Site):
    name = "inkbunny"
    pattern = re.compile(
        r"https?://(?:www\.)?inkbunny\.net/"
        r"(?:s/|submissionview\.php\?id=)(\d+)(?:-p\d+-)?(?:#.*)?",
    )

    sid: str
    login: dict[str, str]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        with open("config/crosspost/inkbunny.toml") as fp:
            self.login = toml.load(fp)

    async def load(self):
        if sid := self.cog.bot.extra.get("crosspost_inkbunny_sid"):
            self.sid = sid
        else:
            url = API_FMT.format("login")
            async with self.cog.get(url, method="POST", params=self.login) as resp:
                json = resp.json()
            self.sid = self.cog.bot.extra["crosspost_inkbunny_sid"] = json["sid"]

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, sub_id: str):
        url = API_FMT.format("submissions")
        params = {
            "sid": self.sid,
            "submission_ids": sub_id,
            "show_description": "yes",
        }

        async with self.cog.get(url, method="POST", params=params) as resp:
            response = resp.json()

        if not (subs := response["submissions"]):
            queue.push_text(
                "Post not found. It may be private.",
                quote=False,
                force=True,
            )
            return

        sub = subs[0]

        queue.author = sub["user_id"]
        queue.link = f"https://inkbunny.net/s/{sub_id}"

        for file in sub["files"]:
            url = file["file_url_full"]
            queue.push_file(url)

        title = sub["title"]
        description = sub["description"].strip()
        queue.push_text(title, bold=True)
        if description:
            description = translate_bbcode(description)
            queue.push_text(description, escape=False)
