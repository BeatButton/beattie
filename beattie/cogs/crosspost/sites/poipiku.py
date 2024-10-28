from __future__ import annotations

import asyncio
import re
import toml
from typing import TYPE_CHECKING

import requests
from lxml import html

import discord

from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..fragment import FileFragment
    from ..queue import FragmentQueue


POIPIKU_URL_GROUPS = re.compile(r"https?://poipiku\.com/(\d+)/(\d+)\.html")


class Poipiku(Site):
    name = "poipiku"
    pattern = re.compile(r"https?://poipiku\.com/\d+/\d+\.html")

    headers: dict[str, str]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        with open("config/headers.toml") as fp:
            headers = toml.load(fp)
        self.session = requests.Session()
        with open("config/crosspost/poipiku.toml") as fp:
            data = toml.load(fp)
            for key, value in data.items():
                self.session.cookies.set(key, value)
        self.session.cookies.set("POIPIKU_CONTENTS_VIEW_MODE", "1")

        for k, v in headers.items():
            self.session.headers[k] = v

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        resp = await asyncio.to_thread(self.session.get, link)
        root = html.document_fromstring(resp.content, self.cog.parser)

        link = str(resp.url)
        if (match := POIPIKU_URL_GROUPS.match(link)) is None:
            return False

        refer = {"Referer": link}

        img = root.xpath(".//img[contains(@class, 'IllustItemThumbImg')]")[0]
        src: str = img.get("src")

        if "/img/" not in src:
            src = src.removesuffix("_640.jpg").replace("//img.", "//img-org.")
            src = f"https:{src}"
            self.push_file(queue, src, link)

        user, post = match.groups()

        queue.author = user

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://poipiku.com",
            **refer,
        }

        body = {
            "UID": user,
            "IID": post,
            "PAS": "",
            "MD": "0",
            "TWF": "-1",
        }

        resp = await asyncio.to_thread(
            self.session.post,
            "https://poipiku.com/f/ShowAppendFileF.jsp",
            headers=headers,
            data=body,
        )
        data = resp.json()

        frag = data["html"]
        if not frag:
            return

        if frag == "You need to sign in.":
            queue.push_text("Post requires authentication.", quote=False, force=True)
            return

        if frag == "Error occurred.":
            queue.push_text(
                "Poipiku reported a generic error.", quote=False, force=True
            )
            return

        if frag == "Password is incorrect.":

            def check(m: discord.Message):
                return (
                    (r := m.reference) is not None
                    and r.message_id == msg.id
                    and m.author.id == ctx.author.id
                )

            async def clean():
                if can_clean:
                    for msg in to_clean:
                        await msg.delete()

            if isinstance(ctx.me, discord.Member):
                can_clean = ctx.channel.permissions_for(ctx.me).manage_messages
            else:
                can_clean = False

            delete_after = 10 if can_clean else None

            msg = await ctx.reply(
                "Post requires a password. Reply to this message with the password.",
                mention_author=True,
            )
            to_clean = [msg]

            while True:
                try:
                    reply = await ctx.bot.wait_for("message", check=check, timeout=60)
                except asyncio.TimeoutError:
                    await ctx.send(
                        "Poipiku password timeout expired.", delete_after=delete_after
                    )
                    await clean()

                to_clean.append(reply)

                body["PAS"] = reply.content

                resp = await asyncio.to_thread(
                    self.session.post,
                    "https://poipiku.com/f/ShowAppendFileF.jsp",
                    headers=headers,
                    data=body,
                )
                data = resp.json()

                frag = data["html"]

                if frag == "Password is incorrect.":
                    msg = await reply.reply(
                        "Incorrect password. Try again, replying to this message.",
                        mention_author=True,
                    )
                    to_clean.append(msg)
                else:
                    await clean()
                    break

        if frag == "Error occurred.":
            queue.push_text(
                "Poipiku reported a generic error.", quote=False, force=True
            )
            return

        root = html.document_fromstring(frag, self.cog.parser)

        for img in root.xpath(".//img"):
            src = img.get("src")
            src = src.removesuffix("_640.jpg").replace("//img.", "//img-org.")
            src = f"https:{src}"
            self.push_file(queue, src, link)

    def push_file(self, queue: FragmentQueue, link: str, referer: str):
        frag = queue.push_file(link)
        frag.dl_task = asyncio.create_task(self.save(frag, referer))

    async def save(self, frag: FileFragment, referer: str):
        resp = await asyncio.to_thread(
            self.session.get, frag.urls[0], headers={"Referer": referer}
        )
        frag.file_bytes = resp.content
