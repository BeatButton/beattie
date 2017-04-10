import random

from discord.ext import commands
from lxml import etree


class NSFW:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['gel'], hidden=True)
    async def gelbooru(self, ctx, *, tags=''):
        async with ctx.typing():
            url = await self.booru('http://gelbooru.com/index.php', tags)
            await ctx.send(url)

    @commands.command(aliases=['r34'], hidden=True)
    async def rule34(self, ctx, *, tags=''):
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
        async with ctx.typing():
            url = await self.booru('https://e621.net/post/index.xml',
                                   tags, limit=240)
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
            root = etree.fromstring(await resp.read(), etree.HTMLParser())
        # We check for posts and images because some booru APIs are different
        posts = root.findall('.//post')
        for post in posts:
            image = next((item[1] for item in post.items()
                         if item[0] == 'file_url'), None)
            if image is not None:
                entries.append(image)
        images = root.findall('.//file_url')
        for image in images:
            entries.append(image.text)
        try:
            url = random.choice(entries)
        except IndexError:
            return 'No images found.'
        else:
            if not url.startswith('http'):
                url = f'https:{url}'
            return url


def setup(bot):
    bot.add_cog(NSFW(bot))
