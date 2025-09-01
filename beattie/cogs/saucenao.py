from __future__ import annotations

from typing import TYPE_CHECKING

from lxml import etree

from discord import Message
from discord.ext import commands
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext


class SauceNao(Cog):
    sauce_url = "https://saucenao.com/search.php"

    def __init__(self, bot: BeattieBot):
        self.session = bot.session
        self.parser = etree.HTMLParser()

    @commands.command(aliases=["sauce"])
    async def saucenao(self, ctx: BContext, *, link: str = None):
        """Find the source of a linked or attached image using saucenao."""
        async with ctx.typing():
            if link is None:
                if (ref := ctx.message.reference) and isinstance(
                    resolved := ref.resolved,
                    Message,
                ):
                    reply = resolved
                else:
                    reply = None
                if len(ctx.message.attachments) == 1:
                    link = ctx.message.attachments[0].url
                elif reply and (attachments := reply.attachments):
                    link = attachments[0].url
                elif (
                    reply
                    and (embeds := reply.embeds)
                    and (url := embeds[0].url) is not None
                ):
                    link = url
                else:
                    raise commands.BadArgument
            elif ctx.message.attachments:
                raise commands.BadArgument

            link = link.strip("<>")
            payload = {"url": link}

            resp = await self.session.post(self.sauce_url, data=payload)
            text = resp.text

            root = etree.fromstring(text, self.parser)

            results = root.xpath('.//div[@class="result"]')
            link = None
            similarity = ""
            if isinstance(results, list) and results:
                result = results[0]
                el = result.find(".//div[@class='resultsimilarityinfo']")
                similarity = el.text
                sim_percent = float(similarity[:-1])
                if sim_percent > 60:
                    result = results[0]
                    if booru := result.find('.//div[@class="resultmiscinfo"]/a'):
                        link = booru.get("href")
                    else:
                        source = result.find('.//div[@class="resultcontentcolumn"]/a')
                        link = source.get("href")

            if link is not None:
                await ctx.send(f"Sauce found ({similarity}) <{link}>")
            else:
                await ctx.send("No sauce found.")

    @saucenao.error
    async def saucenao_error(self, ctx: BContext, e: Exception):
        if isinstance(e, commands.BadArgument):
            await ctx.send("Please include a link or attach a single image.")
        else:
            await ctx.bot.handle_error(ctx, e)


async def setup(bot: BeattieBot):
    await bot.add_cog(SauceNao(bot))
