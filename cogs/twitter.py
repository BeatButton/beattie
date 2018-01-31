from io import BytesIO
import re

import aiohttp
from lxml import etree
import yaml

from discord.ext import commands
from discord import File

from utils.contextmanagers import get as _get

class Twitter:
    """Contains the capability to link images from tweets and other social media"""
    twit_url_expr = re.compile(r'https?:\/\/twitter\.com\/\S+\/status\/\d+')
    tweet_selector = ".//div[contains(@class, 'tweet permalink-tweet')]"
    twit_img_selector = './/img[@data-aria-label-part]'

    pixiv_url_expr = re.compile(r'https?:\/\/www\.pixiv\.net\/member_illust\.php\??(?:&?[^=&]*=[^=&>]*)*')
    pixiv_img_selector = ".//img[@class='original-image']"
    pixiv_read_more_selector = ".//a[contains(@class, 'read-more')]"
    pixiv_manga_page_selector = ".//div[contains(@class, 'item-container')]/a"

    hiccears_url_expr = re.compile(r'https?:\/\/hiccears\.com\/(?:(?:gallery)|(?:picture))\.php\?(?:g|p)id=\d+')
    hiccears_link_selector = ".//div[contains(@class, 'row')]//a"
    hiccears_img_selector = ".//a[contains(@href, 'imgs')]"

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

    async def __init(self):
        await self.bot.wait_until_ready()
        if not self.bot.user.bot:
            self.bot.unload_extension(__name__)

    def __unload(self):
        self.session.close()

    def get(self, *args, **kwargs):
        headers = self.headers.copy()
        headers.update(kwargs.pop('headers', {}))
        return _get(self.session, *args, headers=headers, **kwargs)

    async def on_message(self, message):
        if message.guild is None:
            return
        if message.author == self.bot.user:
            return
        if not (await self.bot.config.get(message.guild.id)).get('twitter'):
            return
        for link in self.twit_url_expr.findall(message.content):
            await self.display_twitter_images(link, message.channel)
        for link in self.pixiv_url_expr.findall(message.content):
            await self.display_pixiv_images(link, message.channel)
        for link in self.hiccears_url_expr.findall(message.content):
            await self.display_hiccears_images(link, message.channel)

    async def display_twitter_images(self, link, destination):
        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)
        try:
            tweet = root.xpath(self.tweet_selector)[0]
        except IndexError:
            return
        for img_link in tweet.findall(self.twit_img_selector)[1:]:
            url = img_link.get('src')
            await destination.send(f'{url}:large')

    async def display_pixiv_images(self, link, destination):
        link = re.sub('(?<=mode=)\w+', 'medium', link)
        link = link.replace('http://', 'https://')
        request = self.get(link)
        async with request as resp:
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
                async with self.get(img_url, headers=heads) as img_resp:
                    content = await img_resp.read()
                img = BytesIO()
                img.write(content)
                img.seek(0)
                file = File(img, filename)
                await destination.send(file=file)
            num = len(pages) - 4
            if num > 0:
                s = 's' if num > 1 else ''
                message = f'{num} more image{s} at <{manga_url}>'
                await destination.send(message)
        else:
            heads = {'referer': link}
            heads.update(self.headers)
            img_elem = root.xpath(self.pixiv_img_selector)[0]
            url = img_elem.get('data-src')
            filename = url.rpartition('/')[2]
            img_request = self.get(url, headers=heads)
            async with img_request as resp:
                content = await resp.read()
            img = BytesIO()
            img.write(content)
            img.seek(0)
            file = File(img, filename)
            await destination.send(file=file)

    async def display_hiccears_images(self, link, destination):
        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)
        single_image = root.xpath(self.hiccears_img_selector)
        if single_image:
            a = single_image[0]
            href = a.get('href')
            url = f'https://{resp.host}{href}'
            await destination.send(url)
            return


        images = root.xpath(self.hiccears_link_selector)
        for image in images [:5]:
            href = image.get('href')
            url = f'https://{resp.host}{href[1:]}'
            async with self.get(url) as page_resp:
                page = etree.fromstring(await page_resp.read(), self.parser)
            a = page.xpath(self.hiccears_img_selector)[0]
            href = a.get('href')
            url = f'https://{resp.host}{href}'
            await destination.send(url)
        num = len(images) - 5
        if num > 0:
            s = 's' if num > 1 else ''
            message = f'{num} more image{s} at <{link}>'
            await destination.send(message)
            

    @commands.command()
    async def twitter(self, ctx, enabled: bool=True):
        """Enable or disable sending non-previewed Twitter images."""
        await self.bot.config.set(ctx.guild.id, twitter=enabled)
        fmt = 'en' if enabled else 'dis'
        await ctx.send(f'Sending Twitter images {fmt}abled.')


def setup(bot):
    bot.add_cog(Twitter(bot))
