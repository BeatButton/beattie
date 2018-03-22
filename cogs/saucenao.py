from lxml import etree

from discord.ext import commands

class SauceNao:
    sauce_url = 'https://saucenao.com/search.php'

    def __init__(self, bot):
        self.session = bot. session
        self.parser = etree.HTMLParser()

    @commands.command(aliases=['sauce'])
    async def saucenao(self, ctx, *, link=''):
        async with ctx.typing():
            if not link:
                if len(ctx.message.attachments) == 1:
                    link = ctx.message.attachments[0].url
                else:
                    raise commands.BadArgument
            elif ctx.message.attachments:
                raise commands.BadArgument
    
            link = link.strip('<>')
            payload = {'url': link}
    
            async with self.session.post(self.sauce_url, data=payload) as resp:
                root = etree.fromstring(await resp.text(), self.parser)
    
            results = root.xpath('.//div[@class="resultcontentcolumn"]/a')
            sim_percent = 0
            if results:
                similarity = root.find(".//div[@class='resultsimilarityinfo']").text
                sim_percent = float(similarity[:-1])
    
            if not results or sim_percent <= 60:
                await ctx.send('No sauce found.')
            else:
                await ctx.send(f'Sauce found ({similarity}) <{results[0].get("href")}>')

    @saucenao.error
    async def saucenao_error(self, ctx, e):
        if isinstance(e, commands.BadArgument):
            await ctx.send('Please include a link or attach a single image.')
        else:
            await ctx.bot.handle_error(ctx, e)


def setup(bot):
    bot.add_cog(SauceNao(bot))
