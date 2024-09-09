from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from lxml import html

import discord
from yarl import URL

from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


POIPIKU_URL_GROUPS = re.compile(r"https?://poipiku\.com/(\d+)/(\d+)\.html")


class Poipiku(Site):
    name = "poipiku"
    pattern = re.compile(r"https?://poipiku\.com/\d+/\d+\.html")

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        cog.bot.session.cookie_jar.update_cookies(
            {"POIPIKU_CONTENTS_VIEW_MODE": "1"}, URL("https://poipiku.com")
        )

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        async with self.cog.get(link, use_default_headers=False) as resp:
            root = html.document_fromstring(await resp.read(), self.cog.parser)

        link = str(resp.url)
        if (match := POIPIKU_URL_GROUPS.match(link)) is None:
            return False

        refer = {"Referer": link}

        img = root.xpath(".//img[contains(@class, 'IllustItemThumbImg')]")[0]
        src: str = img.get("src")

        if "/img/" not in src:
            src = src.removesuffix("_640.jpg").replace("//img.", "//img-org.")
            src = f"https:{src}"
            queue.push_file(src, headers=refer)

        user, post = match.groups()

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

        async with self.cog.get(
            "https://poipiku.com/f/ShowAppendFileF.jsp",
            method="POST",
            use_default_headers=False,
            headers=headers,
            data=body,
        ) as resp:
            data = await resp.json()

        frag = data["html"]
        if not frag:
            return

        if frag == "You need to sign in.":
            queue.push_text("Post requires authentication.", force=True)
            return

        if frag == "Error occurred.":
            queue.push_text("Poipiku reported a generic error.", force=True)
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

                async with self.cog.get(
                    "https://poipiku.com/f/ShowAppendFileF.jsp",
                    method="POST",
                    use_default_headers=False,
                    headers=headers,
                    data=body,
                ) as resp:
                    data = await resp.json()

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
            queue.push_text("Poipiku reported a generic error.", force=True)
            return

        root = html.document_fromstring(frag, self.cog.parser)

        for img in root.xpath(".//img"):
            src = img.get("src")
            src = src.removesuffix("_640.jpg").replace("//img.", "//img-org.")
            src = f"https:{src}"
            queue.push_file(src, headers=refer)
