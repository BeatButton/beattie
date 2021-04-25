from discord.ext import commands
from discord.ext.commands import Cog
from lxml import etree

from bot import BeattieBot
from context import BContext


class SauceNao(Cog):
    sauce_url = "https://saucenao.com/search.php"

    def __init__(self, bot: BeattieBot):
        self.session = bot.session
        self.parser = etree.HTMLParser()

    @commands.command(aliases=["sauce"])
    async def saucenao(self, ctx: BContext, *, link: str = "") -> None:
        """Find the source of a linked or attached image using saucenao."""
        async with ctx.typing():
            if not link:
                if len(ctx.message.attachments) == 1:
                    link = ctx.message.attachments[0].url
                else:
                    raise commands.BadArgument
            elif ctx.message.attachments:
                raise commands.BadArgument

            link = link.strip("<>")
            payload = {"url": link}

            async with self.session.post(self.sauce_url, data=payload) as resp:
                root = etree.fromstring(await resp.text(), self.parser)

            results = root.xpath('.//div[@class="result"]')
            result = None
            sim_percent = 0.0
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
    async def saucenao_error(self, ctx: BContext, e: Exception) -> None:
        if isinstance(e, commands.BadArgument):
            await ctx.send("Please include a link or attach a single image.")
        else:
            await ctx.bot.handle_error(ctx, e)


def setup(bot: BeattieBot) -> None:
    bot.add_cog(SauceNao(bot))
