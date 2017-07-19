import random
import re

import discord
from discord.ext import commands
from lxml import etree


class NSFW:
    def __init__(self, bot):
        self.cache = {}
        self.titles = {}
        self.get = bot.get
        self.log = bot.logger.debug

    @commands.command(aliases=['gel'], hidden=True)
    async def gelbooru(self, ctx, *, tags=''):
        async with ctx.typing():
            await self.booru(ctx, 'http://gelbooru.com/index.php', tags)

    @commands.command(aliases=['r34'], hidden=True)
    async def rule34(self, ctx, *, tags=''):
        async with ctx.typing():
            await self.booru(ctx, 'http://rule34.xxx/index.php', tags)

    @commands.command(hidden=True)
    async def shota(self, ctx, *, tags=''):
        async with ctx.typing():
            await self.booru(ctx, 'http://booru.shotachan.net/post/index.xml',
                             tags)

    @commands.command(aliases=['fur'], hidden=True)
    async def e621(self, ctx, *, tags=''):
        async with ctx.typing():
            await self.booru(ctx, 'https://e621.net/post/index.xml',
                             tags, limit=240)

    @commands.command(hidden=True)
    async def massage(self, ctx, *, tags=''):
        await ctx.invoke(self.gelbooru, tags=f'massage {tags}')

    async def booru(self, ctx, url, tags, limit=100):
        tags = tuple(sorted(tags.split()))
        try:
            self.titles[url]
        except KeyError:
            await self.set_metadata(url)
        try:
            posts = self.cache.setdefault(url, {})[tags]
        except KeyError:
            params = {'page': 'dapi',
                      's': 'post',
                      'q': 'index',
                      'limit': limit,
                      'tags': ' '.join(tags)}
            async with ctx.bot.get(url, params=params) as resp:
                root = etree.fromstring(await resp.read(), etree.HTMLParser())
            posts = root.findall('.//post')
            random.shuffle(posts)
            self.cache[url][tags] = posts
        if not posts:
            await ctx.send('No images found.')
            return
        embed, file = self.make_embed(posts.pop(), url)
        await ctx.send(embed=embed, file=file)
        if not posts:
            self.cache[url].pop(tags, None)

    def make_embed(self, post_element, url):
        post = dict(post_element.items())
        if not post:
            post = {child.tag: child.text
                    for child in post_element.getchildren()}
        embed = discord.Embed()
        pattern = r'https?:\/\/(?:[\w\d]+\.)*([\w\d]+)\.'
        name = re.match(pattern, url).groups()[0]
        file = discord.File(f'data/favicons/{name}.png', 'favicon.png')
        embed.set_thumbnail(url=f'attachment://favicon.png')
        try:
            image = post['file_url']
        except KeyError:
            image = post['jpeg_url']
        if not image.startswith('http'):
            if not image.startswith('//'):
                image = f'//{image}'
            image = f'https:{image}'
        self.log(f'booru url: {image}')
        embed.set_image(url=image)
        embed.title = self.titles[url]
        try:
            source = post['source']
        except KeyError:
            pass
        else:
            embed.url = source
        return embed, file

    async def set_metadata(self, url):
        base = re.match(r'(https?:\/\/[\w\d\.]+\/)', url).groups()[0]
        async with self.get(base) as resp:
            root = etree.fromstring(await resp.read(), etree.HTMLParser())
        self.titles[url] = root.find('.//title').text


def setup(bot):
    bot.add_cog(NSFW(bot))
