from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from discord import Color, Embed
from discord.ext import commands
from discord.ext.commands import Cog

from beattie.utils.exceptions import ResponseError
from beattie.utils.paginator import Paginator

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext
    from beattie.utils.contextmanagers import get

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
        self.last_request = datetime.now().astimezone() - DELAY
        self.logger = logging.getLogger(__name__)

    async def request(self, endpoint: str, **kwargs: Any) -> get:
        async with self.lock:
            now = datetime.now().astimezone()

            if (diff := now - self.last_request) < DELAY:
                secs = diff.total_seconds()
                self.logger.info(f"sleeping for {secs} seconds")
                await asyncio.sleep(secs)
                now += diff
            self.last_request = now
            return self.bot.get(f"{API}/{endpoint}", **kwargs)

    @commands.command()
    async def scry(self, ctx: BContext, *, query: str):
        """Search for cards on Scryfall"""
        params = {"q": query}
        try:
            async with (
                ctx.typing(),
                await self.request("cards/search", params=params) as resp,
            ):
                data = resp.json()
        except ResponseError as e:
            if e.code == 404:
                await ctx.send("No cards found.")
                return
            raise

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
                        f"{card['name']} had neither image_uris nor card_faces",
                    )
                    return

            embed.set_image(url=uris["large"])

            if (colors := card.get("colors")) is None:
                if faces := card.get("card_faces"):
                    colors = list({color for face in faces for color in face["colors"]})
                else:
                    await ctx.send(f"{card['name']} had neither colors nor card_faces")
                    return

            match colors:
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
            embed.set_footer(text=f"Page {i}/{size}")
            embeds.append(embed)
        if size == 1:
            embed.set_footer(text=None)
        paginator = Paginator(embeds)
        await paginator.start(ctx)


async def setup(bot: BeattieBot):
    await bot.add_cog(Scryfall(bot))
