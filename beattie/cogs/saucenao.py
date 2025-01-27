from __future__ import annotations

from typing import TYPE_CHECKING
from discord import Message
from discord.ext import commands
from discord.ext.commands import Cog
from lxml import etree

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
                    resolved := ref.resolved, Message
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

            resp = None
            try:
                resp = await self.session.post(
                    self.sauce_url, data=payload, stream=True
                )
                text = await resp.text or ""
            finally:
                if resp is not None:
                    await resp.close()

            root = etree.fromstring(text, self.parser)

            results = root.xpath('.//div[@class="result"]')
            result = None
            sim_percent = 0.0
            source_link = None
            similarity = ""
            if len(results):
                similarity = root.find(".//div[@class='resultsimilarityinfo']").text
                sim_percent = float(similarity[:-1])
                if sim_percent > 60:
                    result = results[0]
                    source_link = result.find('.//div[@class="resultcontentcolumn"]/a')

            if source_link is None:
                await ctx.send("No sauce found.")
            else:
                result = results[0]
                if (
                    booru_link := result.find('.//div[@class="resultmiscinfo"]/a')
                ) is not None:
                    link = f"<{booru_link.get('href')}>"
                else:
                    link = f"<{source_link.get('href')}>"

                await ctx.send(f"Sauce found ({similarity}) {link}")

    @saucenao.error
    async def saucenao_error(self, ctx: BContext, e: Exception):
        if isinstance(e, commands.BadArgument):
            await ctx.send("Please include a link or attach a single image.")
        else:
            await ctx.bot.handle_error(ctx, e)


async def setup(bot: BeattieBot):
    await bot.add_cog(SauceNao(bot))
