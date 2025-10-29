from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING, TypedDict

import httpx
import toml
from lxml import html

import discord

from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..fragment import FileFragment
    from ..queue import FragmentQueue

    class Response(TypedDict):
        html: str
        error_code: int


POIPIKU_URL_GROUPS = re.compile(r"https?://poipiku\.com/(\d+)/(\d+)\.html")


class Poipiku(Site):
    name = "poipiku"
    pattern = re.compile(r"https?://poipiku\.com/\d+/\d+\.html")
    concurrent = False

    headers: dict[str, str]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        with open("config/headers.toml") as fp:
            headers = toml.load(fp)
        self.session = httpx.AsyncClient(follow_redirects=True, timeout=None)
        cookies = self.session.cookies
        with open("config/crosspost/poipiku.toml") as fp:
            data = toml.load(fp)
            for key, value in data.items():
                cookies.set(key, value)
        cookies.set("POIPIKU_CONTENTS_VIEW_MODE", "1")

        for k, v in headers.items():
            self.session.headers[k] = v

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        resp = await self.session.get(link)
        root = html.document_fromstring(resp.content)
        link = str(resp.url)

        if (match := POIPIKU_URL_GROUPS.match(link)) is None:
            return

        user, post = match.groups()

        queue.author = user

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://poipiku.com",
            "Referer": link,
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        body = {
            "ID": user,
            "TD": post,
            "AD": "-1",
            "PAS": "",
        }

        resp = await self.session.post(
            "https://poipiku.com/f/ShowIllustDetailF.jsp",
            headers=headers,
            data=body,
        )
        data: Response = resp.json()

        frag = data["html"]
        error_code = data["error_code"]

        if error_code == -3:

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
                    ctx.bot.shared.create_task(
                        ctx.send(
                            "Poipiku password timeout expired.",
                            delete_after=delete_after,
                        ),
                    )
                    ctx.bot.shared.create_task(clean())
                    raise

                to_clean.append(reply)

                body["PAS"] = reply.content

                resp = await self.session.post(
                    "https://poipiku.com/f/ShowIllustDetailF.jsp",
                    headers=headers,
                    data=body,
                )
                data: Response = resp.json()

                frag = data["html"]
                error_code = data["error_code"]

                if error_code == -3:
                    msg = await reply.reply(
                        "Incorrect password. Try again, replying to this message.",
                        mention_author=True,
                    )
                    to_clean.append(msg)
                else:
                    ctx.bot.shared.create_task(clean())
                    break

        if error_code != 0:
            queue.push_text(
                f"Uninterpreted poipiku error code: {error_code}",
                quote=False,
                force=True,
            )
            return

        root = html.document_fromstring(frag)

        for img in root.xpath(".//img"):
            self.push_file(queue, img.get("src"), link)

    def push_file(self, queue: FragmentQueue, link: str, referer: str):
        if not link.startswith("https:"):
            link = f"https:{link}"
        frag = queue.push_file(link)
        frag.dl_task = asyncio.create_task(self.save(frag, referer))

    async def save(self, frag: FileFragment, referer: str):
        wait = 1
        while True:
            resp = await self.session.get(frag.urls[0], headers={"Referer": referer})

            if not resp.content.startswith(b"<html>"):
                break

            await asyncio.sleep(wait)
            wait *= 2

        frag.file_bytes = resp.content
