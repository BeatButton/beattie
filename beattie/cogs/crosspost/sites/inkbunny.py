from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypedDict

import toml

from beattie.utils.etc import translate_bbcode
from beattie.utils.exceptions import ResponseError

from ..database_types import TextLength
from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class File(TypedDict):
        file_url_full: str
        file_url_screen: str

    class Submission(TypedDict):
        user_id: str
        files: list[File]
        title: str
        description: str

    class Response(TypedDict):
        submissions: list[Submission]


API_FMT = "https://inkbunny.net/api_{}.php"


class Inkbunny(Site):
    name = "inkbunny"
    pattern = re.compile(
        r"https?://(?:www\.)?inkbunny\.net/"
        r"(?:s/|submissionview\.php\?id=)(\d+)(?:-p\d+-)?(?:#.*)?",
    )

    sid: str

    async def load(self):
        if sid := self.cog.bot.extra.get("crosspost_inkbunny_sid"):
            self.sid = sid
        else:
            with open("config/crosspost/inkbunny.toml") as fp:
                params = toml.load(fp)
            async with self.cog.get(
                API_FMT.format("login"),
                method="POST",
                params=params,
            ) as resp:
                json = resp.json()
            self.sid = self.cog.bot.extra["crosspost_inkbunny_sid"] = json["sid"]

    async def handler(self, _ctx: CrosspostContext, queue: FragmentQueue, sub_id: str):
        url = API_FMT.format("submissions")
        params = {
            "sid": self.sid,
            "submission_ids": sub_id,
            "show_description": "yes",
        }

        async with self.cog.get(url, method="POST", params=params) as resp:
            response: Response = resp.json()

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
            full = file["file_url_full"]
            screen = file["file_url_screen"]
            queue.push_fallback(full, screen, headers={"Referer": queue.link})

        title = sub["title"]
        description = sub["description"].strip()
        queue.push_text(title, bold=True)
        if description:
            description = translate_bbcode(description)
            queue.push_text(description, escape=False, length=TextLength.LONG)
