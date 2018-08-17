import asyncio
from collections import defaultdict 
from io import BytesIO, StringIO
import json
import re
import traceback

import aiohttp
import arsenic
from arsenic.browsers import Firefox
from arsenic.errors import ArsenicTimeout, NoSuchElement
from arsenic.services import Geckodriver
from lxml import etree
import yaml

from discord.ext import commands
from discord import File, HTTPException

from context import BContext
from utils.contextmanagers import get as _get

class TwitContext(BContext):
    async def send(self, *args, **kwargs):
        msg = await super().send(*args, **kwargs)
        self.bot.get_cog('Twitter').record[self.message.id].append(msg)
        return msg

class Twitter:
    """Contains the capability to link images from tweets and other social media"""
    twitter_url_expr = re.compile(r'https?://(?:www\.)?twitter\.com/\S+/status/\d+')
    tweet_selector = 'div.tweet.permalink-tweet'
    twitter_img_selector = 'img[data-aria-label-part]'

    pixiv_url_expr = re.compile(r'https?://(?:www\.)?pixiv\.net/member_illust\.php\??(?:&?[^=&]*=[^=&>\s]*)*')
    pixiv_login_selector = 'a[href*="accounts.pixiv.net/login"]'
    pixiv_img_selector = 'a[href*="img"]'
    pixiv_read_more_selector = 'a[href*="mode=manga"]'
    pixiv_manga_page_selector = 'a.full-size-container'
    pixiv_spoiler_selector = 'button.EZLF3WY'

    hiccears_url_expr = re.compile(r'https?://(?:www\.)?hiccears\.com/(?:(?:gallery)|(?:picture))\.php\?[gp]id=\d+')
    hiccears_link_selector = ".//div[contains(@class, 'row')]//a"
    hiccears_img_selector = ".//a[contains(@href, 'imgs')]"

    tumblr_url_expr = re.compile(r'https?://[\w-]+\.tumblr\.com/post/\d+')
    tumblr_img_selector = ".//meta[@property='og:image']"

    def __init__(self, bot):
        self.bot = bot
        self.headers = {'User-Agent':
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:60.0) '
                        'Gecko/20100101 Firefox/60.0'}
        with open('config/cookies.yaml') as fp:
            self.cookies = yaml.load(fp)
        with open('config/logins.yaml') as fp:
            self.logins = yaml.load(fp)
        self.session = aiohttp.ClientSession(loop=bot.loop, cookies=self.cookies)
        self.parser = etree.HTMLParser()
        names = (name.partition('_')[0] for name in vars(type(self)) if name.endswith('url_expr'))
        self.expr_dict = {getattr(self, f'{name}_url_expr'): getattr(self, f'display_{name}_images')
                          for name in names}
        self.record = defaultdict(list)
        self.arsenic_session = None
        self.ready = False

    def __local_check(self, ctx):
        return self.ready

    async def __init(self):
        await self.bot.wait_until_ready()
        if not self.bot.user.bot:
            self.bot.unload_extension(__name__)
        else:
            service = Geckodriver(binary='geckodriver', log_file=None)
            browser = Firefox(**{'moz:firefoxOptions': {'args': ['-headless']}})
            self.arsenic_session = await arsenic.start_session(service, browser)
            self.get_session = self._get_context_manager()
            self.ready = True
        
    def __unload(self):
        if self.arsenic_session is not None:
            self.bot.loop.create_task(arsenic.stop_session(self.arsenic_session))
        self.bot.loop.create_task(self.session.close())

    def _get_context_manager(self):
        session = self.arsenic_session
        cookies = self.cookies
        class get_session(asyncio.Lock):
            def __init__(self, link):
                super().__init__()
                self.link = link
        
            async def __aenter__(self):
                await super().__aenter__()
                await session.get(self.link)
                for name, value in cookies.items():
                    await session.add_cookie(name, value)
                await session.get(self.link)
                session.release = self.release
                return session

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                await super().__aexit__(exc_type, exc_val, exc_tb)

        return get_session
                
    def get(self, *args, **kwargs):
        kwargs['headers'] = {**self.headers, **kwargs.get('headers', {})}
        return _get(self.session, *args, **kwargs)

    async def on_message(self, message):
        if self.arsenic_session is None:
            self.arsenic_session = object()
            await self.__init()
        elif not self.ready:
            await asyncio.sleep(5)
            return await self.on_message(message)
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
                    async with ctx.typing():
                        await func(link, ctx)
                except Exception as e:
                    fp = StringIO()
                    traceback.print_exception(type(e), e, e.__traceback__, file=fp)
                    await ctx.send(f'```py\n{fp.getvalue()}```')

    async def on_message_delete(self, message):
        for msg in self.record[message.id]:
            await msg.delete()
        del self.record[message.id]

    async def display_twitter_images(self, link, ctx):
        async with self.get_session(link) as sess:
            try:
                tweet = await sess.wait_for_element(60, self.tweet_selector)
            except ArsenicTimeout:
                return

            for img in (await tweet.get_elements(self.twitter_img_selector))[1:]:
                url = await img.get_attribute('src')
                await ctx.send(f'{url}:orig')

    async def display_pixiv_images(self, link, ctx):
        if 'mode' in link:
            link = re.sub('(?<=mode=)\w+', 'medium', link)
        else:
            link = f'{link}&mode=medium'
        link = link.replace('http://', 'https://')
        async with self.get_session(link) as sess:
            await sess.wait_for_element(60, 'body')
            try:
                button = await sess.get_element(self.pixiv_login_selector)
            except NoSuchElement:
                pass
            else:
                await button.click()
                creds = self.logins['pixiv']
                user_input_selector = 'input[autocomplete="username"]'
                user_input = await sess.wait_for_element(60, user_input_selector)
                await user_input.send_keys(creds['username'])
                pass_input = await sess.get_element('input[autocomplete*="password"]')
                await pass_input.send_keys(creds['password'])
                await pass_input.send_keys('\ue007') #enter
                try:
                    await sess.wait_for_element(10, 'section div a[href*="member.php"]')
                except ArsenicTimeout:
                    await ctx.send(await sess.get_url())
            try:
                button = await sess.get_element(self.pixiv_spoiler_selector)
            except NoSuchElement:
                pass
            else:
                await button.click()
            try:
                await sess.get_element(self.pixiv_read_more_selector)
            except NoSuchElement:
                heads = {'referer': link}
                heads.update(self.headers)
                try:
                    img_elem = await sess.get_element(self.pixiv_img_selector)
                except NoSuchElement:
                    msg = await ctx.send('Fetching gif...')
                    file = await self.get_ugoira(link)
                    try:
                        await ctx.send(file=file)
                    except HTTPException:
                        await msg.edit(content='Gif too large, fetching webm...')
                        file = await self.get_ugoira(link, fmt='webm')
                        await ctx.send(file=file)
                    await msg.delete()
                else:
                    url = await img_elem.get_attribute('href')
                    filename = url.rpartition('/')[2]
                    img = BytesIO()
                    async with self.get(url, headers=heads) as img_resp:
                        async for chunk in img_resp.content.iter_any():
                            if not chunk:
                                break
                            img.write(chunk)
                    img.seek(0)
                    file = File(img, filename)
                    await ctx.send(file=file)
                return
            else:
                manga_url = link.replace('medium', 'manga')
                await sess.get(manga_url)
                await sess.wait_for_element(60, self.pixiv_manga_page_selector)
                num_pages = len(await sess.get_elements(self.pixiv_manga_page_selector))
                illust = re.search('\d+', link).group()
                for i in range(min(num_pages, 4)):
                    fullsize_url = f'https://pixiv.net/member_illust.php?mode=manga_big&illust_id={illust}&page={i}'
                    await sess.get(fullsize_url)
                    img_url = await (await sess.wait_for_element(60, 'img')).get_attribute('src')
                    filename = img_url.rpartition('/')[2]
                    img = BytesIO()
                    async with sess.connection.session.get(img_url, headers={'referer': fullsize_url}) as img_resp:
                        async for chunk in img_resp.content.iter_any():
                            if not chunk:
                                break
                            img.write(chunk)
                    img.seek(0)
                    file = File(img, filename)
                    await ctx.send(file=file)
                remaining = num_pages - 4
                if remaining > 0:
                    s = 's' if remaining > 1 else ''
                    message = f'{remaining} more image{s} at <{manga_url}>'
                    await ctx.send(message)

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
            await ctx.send(url)
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
