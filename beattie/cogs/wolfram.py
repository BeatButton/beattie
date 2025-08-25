from __future__ import annotations

from typing import TYPE_CHECKING, TypedDict

import toml
from lxml import etree

from discord.ext import commands
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from collections.abc import Mapping

    from beattie.bot import BeattieBot
    from beattie.context import BContext

    class Config(TypedDict):
        key: str


API_URL = "http://api.wolframalpha.com/v2/query"


class Wolfram(Cog):
    chars: Mapping[int, str] = {0xF74C: " d", 0xF74D: "e", 0xF74E: "i", 0xF7D9: " = "}

    def __init__(self):
        with open("config/wolfram.toml") as file:
            data: Config = toml.load(file)  # pyright: ignore[reportAssignmentType]
        self.key = data["key"]

    @commands.command(aliases=["wolf", "w"])
    async def wolfram(self, ctx: BContext, *, inp: str):
        """Query Wolfram|Alpha."""
        async with ctx.typing():
            params = {"input": inp, "appid": self.key, "format": "plaintext"}
            async with ctx.bot.get(API_URL, params=params) as resp:
                text = resp.text
            root = etree.fromstring(text.encode(), etree.XMLParser())
            interpret = root.xpath(
                "//pod[@title='Input interpretation']/subpod/plaintext/text()",
            )
            if not interpret:
                interpret = root.xpath(
                    "//pod[@title='Input']/subpod/plaintext/text()",
                )
            if not interpret:
                interpret = [""]
            interpret = interpret[0]
            try:
                result = root.xpath(
                    "//pod[not(starts-with(@title, 'Input'))]"
                    "/subpod/plaintext/text()",
                )[0]
            except IndexError:
                result = "No results found."
            if interpret:
                result = f"> {interpret}\n{result}"
            result = result.translate(self.chars)
        await ctx.send(result)


async def setup(bot: BeattieBot):
    await bot.add_cog(Wolfram())
