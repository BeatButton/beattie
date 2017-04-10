import random

from discord.ext import commands
from lxml import etree


class NSFW:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['gel'], hidden=True)
    async def gelbooru(self, ctx, *, tags):
        async with ctx.typing():
            url = await self.booru('http://gelbooru.com/index.php', tags)
            await ctx.send(url)

    @commands.command(aliases=['r34'], hidden=True)
    async def rule34(self, ctx, *, tags):
        async with ctx.typing():
            url = await self.booru('http://rule34.xxx/index.php', tags)
            await ctx.send(url)

    @commands.command(hidden=True)
    async def shota(self, ctx, *, tags=''):
        async with ctx.typing():
            url = await self.booru('http://booru.shotachan.net/post/index.xml',
                                   tags)
            await ctx.send(url)

    @commands.command(aliases=['fur'], hidden=True)
    async def e621(self, ctx, *, tags=''):
        url = await self.booru('https://e621.net//post/index.xml', tags, 240)
        await ctx.send(url)

    @commands.command(hidden=True)
    async def massage(self, ctx, *, tags=''):
        await ctx.invoke(self.gelbooru, tags=f'massage {tags}')

    async def booru(self, url, tags, limit=100):
        entries = []
        params = {'page': 'dapi',
                  's': 'post',
                  'q': 'index',
                  'limit': limit,
                  'tags': tags}
        async with self.bot.get(url, params=params) as resp:
            root = etree.fromstring((await resp.text()).encode(),
                                    etree.HTMLParser())
        search_nodes = root.findall(".//post")
        for node in search_nodes:
            image = next((item[1] for item in node.items()
                         if item[0] == 'file_url'), None)
            if image is not None:
                entries.append(image)
        try:
            url = random.choice(entries)
        except IndexError:
            return 'No images found.'
        else:
            if not url.startswith('http:'):
                url = f'http:{url}'
            return url


def setup(bot):
    bot.add_cog(NSFW(bot))
