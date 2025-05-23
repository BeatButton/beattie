from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING, TypedDict

import discord
from discord.ext import commands
from discord.ext.commands import Cog

from beattie.utils.exceptions import ResponseError

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext


class XkcdData(TypedDict):
    num: int
    year: str
    title: str
    img: str
    alt: str


class XKCD(Cog):
    xkcd_data: XkcdData

    def __init__(self):
        with open("data/why.txt", encoding="utf8") as file:
            self.questions: tuple[str, ...] = tuple(file.readlines())

    @commands.command()
    async def why(self, ctx: BContext):
        """Asks a question."""
        await ctx.send(random.choice(self.questions))

    @commands.group()
    async def xkcd(self, ctx: BContext, *, inp: str = None):
        """Commands for getting xkcd comics"""
        async with ctx.typing():
            url = "https://xkcd.com/info.0.json"
            async with ctx.bot.get(url) as resp:
                self.xkcd_data = resp.json()
            if not inp or inp == "random":
                await self.random(ctx)
            elif inp in ("latest", "current"):
                await self.latest(ctx)
            else:
                await self.comic(ctx, inp=inp)

    @xkcd.command()
    async def random(self, ctx: BContext):
        """Gets a random xkcd comic."""
        await self.comic(ctx, inp=str(random.randint(1, self.xkcd_data["num"])))

    @xkcd.command()
    async def latest(self, ctx: BContext):
        """Gets the latest xkcd comic."""
        await ctx.send(embed=format_comic(self.xkcd_data))

    @xkcd.command()
    async def comic(self, ctx: BContext, *, inp: str):
        """Gets an xkcd comic by number or content."""
        try:
            number = int(inp)
        except ValueError:
            url = "https://duckduckgo.com/html/"
            params = {"q": f"{inp} xkcd"}
            async with ctx.bot.get(url, params=params) as resp:
                text = resp.text
            match = re.search(r"xkcd\.com/(\d+)/\s", text)
            if match:
                number = int(match.groups()[0])
            else:
                await ctx.send("No comic found.")
                return
        else:
            if number > self.xkcd_data["num"]:
                await ctx.send("No comic found.")
                return

        url = f"https://xkcd.com/{number}/info.0.json"
        data: XkcdData
        try:
            async with ctx.bot.get(url) as resp:
                data = resp.json()
        except ResponseError:
            data = {
                "title": "404",
                "img": "http://www.explainxkcd.com/wiki/images/9/92/not_found.png",
                "alt": "Comic not found.",
                "num": 404,
                "year": "",
            }
        await ctx.send(embed=format_comic(data))

    @commands.command(hidden=True)
    async def sudo(self, ctx: BContext, *, _: str):
        if await ctx.bot.is_owner(ctx.author):
            await ctx.send("Operation successful.")
        else:
            await ctx.send("Unable to lock /var/lib/dpkg/, are you root?")


def format_comic(data: XkcdData) -> discord.Embed:
    embed = discord.Embed()
    embed.title = data["title"]
    embed.set_image(url=data["img"])
    embed.set_footer(text=data["alt"])
    embed.url = f"https://xkcd.com/{data['num']}/"
    return embed


async def setup(bot: BeattieBot):
    await bot.add_cog(XKCD())
