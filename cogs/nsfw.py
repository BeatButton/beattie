from collections import defaultdict
import random
import re
from urllib import parse

import discord
from discord.ext import commands
from lxml import etree


class NSFW:
    view = {
        'gelbooru': 'https://gelbooru.com/index.php?page=post&s=view&id={}',
        'rule34': 'https://rule34.xxx/index.php?page=post&s=view&id={}',
        'shotachan': 'http://booru.shotachan.net/post/show/{}',
        'e621': 'http://e621.net/post/show/{}',
    }

    urls = {
        'gelbooru': 'http://gelbooru.com/index.php',
        'rule34': 'http://rule34.xxx/index.php',
        'shotachan': 'http://booru.shotachan.net/post/index.xml',
        'e621': 'https://e621.net/post/index.xml',
    }

    def __local_check(self, ctx):
        return ctx.channel.is_nsfw()

    def __init__(self, bot):
        self.cache = defaultdict(dict)
        self.titles = {}
        self.get = bot.get
        self.log = bot.logger.debug

    @commands.command(aliases=['gel'], hidden=True)
    async def gelbooru(self, ctx, *tags=()):
        async with ctx.typing():
            await self.booru(ctx, tags)

    @commands.command(aliases=['r34'], hidden=True)
    async def rule34(self, ctx, *tags=()):
        async with ctx.typing():
            await self.booru(ctx, tags)

    @commands.command(aliases=['shota'], hidden=True)
    async def shotachan(self, ctx, *tags=()):
        async with ctx.typing():
            await self.booru(ctx,
                             tags)

    @commands.command(aliases=['fur'], hidden=True)
    async def e621(self, ctx, *tags=()):
        async with ctx.typing():
            await self.booru(ctx, tags, limit=320)

    @commands.command(hidden=True)
    async def massage(self, ctx, *tags=()):
        await ctx.invoke(self.gelbooru, tags=('massage',) + tags)

    async def booru(self, ctx, tags, limit=100):
        tags = frozenset(tags)
        site = ctx.command.name
        channel = ctx.channel
        if site not in self.titles:
            await self.set_metadata(site)
        try:
            posts = self.cache[channel].setdefault(site, {})[tags]
        except KeyError:
            params = {'page': 'dapi',
                      's': 'post',
                      'q': 'index',
                      'limit': limit,
                      'tags': ' '.join(tags)}
            async with ctx.bot.get(self.urls[site], params=params) as resp:
                root = etree.fromstring(await resp.read())
            posts = root.findall('.//post')
            random.shuffle(posts)
            self.cache[channel][site][tags] = posts
        if not posts:
            await ctx.send('No images found.')
            return
        embed, file = self.make_embed(posts.pop(), site)
        await ctx.send(embed=embed, file=file)
        if not posts:
            self.cache[channel][site].pop(tags, None)

    def make_embed(self, post_element, site):
        post = dict(post_element.items())
        if not post:
            post = {child.tag: child.text
                    for child in post_element.getchildren()}
        embed = discord.Embed()
        file = discord.File(f'data/favicons/{site}.png', 'favicon.png')
        embed.set_thumbnail(url='attachment://favicon.png')
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
        embed.title = self.titles[site]
        embed.url = self.view[site].format(post['id'])
        source = post.get('source')
        if source is not None:
            embed.description = f'[source]({source})'
        return embed, file

    async def set_metadata(self, site):
        url = self.urls[site]
        netloc = parse.urlsplit(url).netloc
        async with self.get(f'https://{netloc}') as resp:
            root = etree.fromstring(await resp.read(), etree.HTMLParser())
        self.titles[site] = root.find('.//title').text


def setup(bot):
    bot.add_cog(NSFW(bot))
