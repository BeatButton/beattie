import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

from discord import Color, Embed
from discord.ext import commands
from discord.ext.commands import Cog

from bot import BeattieBot
from context import BContext
from utils.contextmanagers import get
from utils.exceptions import ResponseError
from utils.paginator import Paginator

API = "https://api.scryfall.com"
DELAY = timedelta(milliseconds=100)


class Scryfall(Cog):
    """Search for cards on Scryfall"""

    bot: BeattieBot
    lock: asyncio.Lock
    last_request: datetime

    def __init__(self, bot: BeattieBot) -> None:
        self.bot = bot
        self.lock = asyncio.Lock()
        self.last_request = datetime.now() - DELAY
        self.logger = logging.getLogger("beattie.scryfall")

    async def request(self, endpoint: str, **kwargs: Any) -> get:
        async with self.lock:
            now = datetime.now()

            if (diff := now - self.last_request) < DELAY:
                secs = diff.total_seconds()
                self.logger.info(f"sleeping for {secs} seconds")
                print(f"scryfall sleeping for {secs} seconds")
                await asyncio.sleep(secs)
                now += diff
            self.last_request = now
            return self.bot.get(f"{API}/{endpoint}", **kwargs)

    @commands.command()
    async def scry(self, ctx: BContext, *, query: str):
        """Search for cards on Scryfall"""
        params = {"q": query}
        try:
            async with ctx.typing(), (
                await self.request("cards/search", params=params)
            ) as resp:
                data = await resp.json()
        except ResponseError as e:
            if e.code == 404:
                await ctx.send("No cards found.")
                return
            raise e

        embeds = []
        cards = data["data"]
        size = len(cards)
        for i, card in enumerate(cards, 1):
            embed = Embed()
            embed.title = card["name"]
            embed.url = card["scryfall_uri"]
            if not (uris := card.get("image_uris")):
                if faces := card.get("card_faces"):
                    uris = faces[0]["image_uris"]
                else:
                    await ctx.send(
                        f"{card['name']} had neither image_uris nor card_faces"
                    )
                    return
            embed.set_image(url=uris["large"])
            match card["colors"]:
                case []:
                    color = Color.light_gray()
                case ["W"]:
                    color = Color.yellow()
                case ["U"]:
                    color = Color.blue()
                case ["B"]:
                    color = Color.purple()
                case ["R"]:
                    color = Color.red()
                case ["G"]:
                    color = Color.green()
                case _:
                    color = Color.gold()
            embed.color = color
            embed.set_footer(text="Page {}/{}".format(i, size))
            embeds.append(embed)
        paginator = Paginator(embeds)
        await paginator.start(ctx)


async def setup(bot: BeattieBot):
    await bot.add_cog(Scryfall(bot))
