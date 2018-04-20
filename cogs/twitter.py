from collections import defaultdict 
from io import BytesIO
import json
import re

import aiohttp
from lxml import etree
import yaml

from discord.ext import commands
from discord import File, HTTPException

from utils.contextmanagers import get as _get


class TwitContext(commands.Context):
    async def send(self, *args, **kwargs):
        msg = await super().send(*args, **kwargs)
        self.bot.get_cog('Twitter').record[self.message.id].append(msg)

class Twitter:
    """Contains the capability to link images from tweets and other social media"""
    twitter_url_expr = re.compile(r'https?://(?:www\.)?twitter\.com/\S+/status/\d+')
    tweet_selector = ".//div[contains(@class, 'tweet permalink-tweet')]"
    twitter_img_selector = './/img[@data-aria-label-part]'

    pixiv_url_expr = re.compile(r'https?://(?:www\.)?pixiv\.net/member_illust\.php\??(?:&?[^=&]*=[^=&>\s]*)*')
    pixiv_img_selector = ".//img[@class='original-image']"
    pixiv_read_more_selector = ".//a[contains(@class, 'read-more')]"
    pixiv_manga_page_selector = ".//div[contains(@class, 'item-container')]/a"

    hiccears_url_expr = re.compile(r'https?://(?:www\.)?hiccears\.com/(?:(?:gallery)|(?:picture))\.php\?[gp]id=\d+')
    hiccears_link_selector = ".//div[contains(@class, 'row')]//a"
    hiccears_img_selector = ".//a[contains(@href, 'imgs')]"

    tumblr_url_expr = re.compile(r'https?://[\w-]+\.tumblr\.com/post/\d+')
    tumblr_img_selector = ".//meta[@property='og:image']"

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.__init())
        self.headers = {'User-Agent':
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:58.0) '
                        'Gecko/20100101 Firefox/58.0'}
        with open('config/cookies.yaml') as fp:
            cookies = yaml.load(fp)
        self.session = aiohttp.ClientSession(loop=bot.loop, cookies=cookies)
        self.parser = etree.HTMLParser()
        names = (name.partition('_')[0] for name in vars(type(self)) if name.endswith('url_expr'))
        self.expr_dict = {getattr(self, f'{name}_url_expr'): getattr(self, f'display_{name}_images')
                          for name in names}
        self.record = defaultdict(list)

    async def __init(self):
        await self.bot.wait_until_ready()
        if not self.bot.user.bot:
            self.bot.unload_extension(__name__)

    def __unload(self):
        self.session.close()

    def get(self, *args, **kwargs):
        kwargs['headers'] = {**self.headers, **kwargs.get('headers', {})}
        return _get(self.session, *args, **kwargs)

    async def on_message(self, message):
        guild = message.guild
        if guild is None:
            return
        if message.author == guild.me:
            return
        if not (await self.bot.config.get(guild.id)).get('twitter'):
            return
        ctx = await self.bot.get_context(message, cls=TwitContext)
        for expr, func in self.expr_dict.items():
            for link in expr.findall(message.content):
                try:
                    await func(link, ctx)
                except Exception as e:
                    await ctx.send(f'Exception in {func.__name__}:\n'
                        f'{type(e).__name__}: {e}')

    async def on_message_delete(self, message):
        for msg in self.record[message.id]:
            await msg.delete()

    async def display_twitter_images(self, link, ctx):
        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)
        try:
            tweet = root.xpath(self.tweet_selector)[0]
        except IndexError:
            return
        for img_link in tweet.findall(self.twitter_img_selector)[1:]:
            url = img_link.get('src')
            await ctx.send(f'{url}:orig')

    async def display_pixiv_images(self, link, ctx):
        if 'mode' in link:
            link = re.sub('(?<=mode=)\w+', 'medium', link)
        else:
            link = f'{link}&mode=medium'
        link = link.replace('http://', 'https://')
        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)
        is_manga = root.xpath(self.pixiv_read_more_selector)
        if is_manga:
            manga_url = link.replace('medium', 'manga')
            heads = {'referer': manga_url}
            heads.update(self.headers)
            async with self.get(manga_url) as resp:
                root = etree.fromstring(await resp.read(), self.parser)
            pages = root.xpath(self.pixiv_manga_page_selector)
            for page in pages[:4]:
                href = page.get('href')
                fullsize_url = f'https://{resp.host}{href}'
                async with self.get(fullsize_url, headers=heads) as page_resp:
                    page_root = etree.fromstring(await page_resp.read(), self.parser)
                page_heads = heads.copy()
                page_heads['referer'] = fullsize_url
                img_url = page_root.find('.//img').get('src')
                filename = img_url.rpartition('/')[2]
                img = BytesIO()
                async with self.get(img_url, headers=heads) as img_resp:
                    async for chunk in img_resp.content.iter_any():
                        if chunk:
                            img.write(chunk)
                img.seek(0)
                file = File(img, filename)
                await ctx.send(file=file)
            num = len(pages) - 4
            if num > 0:
                s = 's' if num > 1 else ''
                message = f'{num} more image{s} at <{manga_url}>'
                await ctx.send(message)
        else:
            heads = {'referer': link}
            heads.update(self.headers)
            img_elem = root.xpath(self.pixiv_img_selector)
            if img_elem:
                img_elem = img_elem[0]
                url = img_elem.get('data-src')
                filename = url.rpartition('/')[2]
                img_request = self.get(url, headers=heads)
                async with img_request as resp:
                    content = await resp.read()
                img = BytesIO()
                img.write(content)
                img.seek(0)
                file = File(img, filename)
                await ctx.send(file=file)
            else:
                msg = await ctx.send('Fetching gif...')
                file = await self.get_ugoira(link)
                try:
                    await ctx.send(file=file)
                except HTTPException:
                    await msg.edit(content='Gif too large, fetching webm...')
                    file = await self.get_ugoira(link, fmt='webm')
                    await ctx.send(file=file)
                await msg.delete()

    async def get_ugoira(self, link, fmt='gif'):
        params = {
            'url': link,
            'format': fmt,
        }
        conv_url = 'http://ugoira.dataprocessingclub.org/convert'
        async with self.get(conv_url, params=params, timeout=None) as resp:
            text = await resp.text()
        url = json.loads(text)['url']
        img = BytesIO()
        async with self.get(url) as resp:
            async for block in resp.content.iter_any():
                if not block:
                    break
                img.write(block)
        img.seek(0)
        name = url.rpartition('/')[2]
        return File(img, name)

    async def display_hiccears_images(self, link, ctx):
        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)
        single_image = root.xpath(self.hiccears_img_selector)
        if single_image:
            a = single_image[0]
            href = a.get('href').lstrip('.')
            url = f'https://{resp.host}{href}'
            await ctx.send(url)
            return

        images = root.xpath(self.hiccears_link_selector)
        for image in images[:4]:
            href = image.get('href')
            url = f'https://{resp.host}{href[1:]}'
            async with self.get(url) as page_resp:
                page = etree.fromstring(await page_resp.read(), self.parser)
            a = page.xpath(self.hiccears_img_selector)[0]
            href = a.get('href')[1:]  # trim leading '.'
            url = f'https://{resp.host}{href}'
            await ctx.send(url)
        num = len(images) - 4
        if num > 0:
            s = 's' if num > 1 else ''
            message = f'{num} more image{s} at <{link}>'
            await ctx.send(message)

    async def display_tumblr_images(self, link, ctx):
        idx = 1
        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)
        if not str(resp.url).startswith(link): # explicit blog redirect
            async with self.bot.session.get(link) as resp: # somehow this doesn't get redirected?
                root = etree.fromstring(await resp.read(), self.parser)
            idx = 0
        images = root.xpath(self.tumblr_img_selector)
        for image in images[idx:4]:
            url = image.get('content')
            raw_url = re.sub(r'https?://\w+\.media',
                             'https://s3.amazonaws.com/data',
                            url)
            raw_url = re.sub(r'_\d+\.',
                             '_raw.',
                             raw_url)
            await ctx.send(raw_url)
        num = len(images) - 4
        if num > 0:
            s = 's' if num > 1 else ''
            message = f'{num} more image{s} at <{link}>'
            await ctx.send(message)

    @commands.command()
    async def twitter(self, ctx, enabled: bool=True):
        """Enable or disable sending non-previewed Twitter images."""
        await self.bot.config.set(ctx.guild.id, twitter=enabled)
        fmt = 'en' if enabled else 'dis'
        await ctx.send(f'Sending Twitter images {fmt}abled.')


def setup(bot):
    bot.add_cog(Twitter(bot))

