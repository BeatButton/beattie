import random

from discord.ext import commands
from lxml import etree


class NSFW:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['gel'], hidden=True)
    async def gelbooru(self, ctx, *, tags):
        async with ctx.typing():
            entries = []
            url = 'http://gelbooru.com/index.php'
            params = {'page': 'dapi',
                      's': 'post',
                      'q': 'index',
                      'tags': tags}
            async with self.bot.session.get(url, params=params) as resp:
                root = etree.fromstring((await resp.text()).encode(),
                                        etree.HTMLParser())
            search_nodes = root.findall(".//post")
            for node in search_nodes:
                image = next((item[1] for item in node.items()
                             if item[0] == 'file_url'), None)
                if image is not None:
                    entries.append(image)
            try:
                message = f'http:{random.choice(entries)}'
            except IndexError:
                message = 'No images found.'
        await ctx.send(message)

    @commands.command(hidden=True)
    async def massage(self, ctx, *, tags=''):
        await ctx.invoke(self.gelbooru, tags='massage ' + tags)


def setup(bot):
    bot.add_cog(NSFW(bot))
