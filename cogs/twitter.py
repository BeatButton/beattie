import asyncio
from collections import defaultdict 
from io import BytesIO, StringIO
import json
import re
import traceback
from typing import Union

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
from utils.checks import is_owner_or
from utils.contextmanagers import get as _get
from utils.exceptions import ResponseError

class TwitContext(BContext):
    async def send(self, *args, **kwargs):
        if kwargs.get('file') is not None:
            if len(kwargs['file'].fp.getvalue()) >= 8_000_000:
                args = ('Image too large to upload.',)
                kwargs = {}
        msg = await super().send(*args, **kwargs)
        self.bot.get_cog('Twitter').record[self.message.id].append(msg)
        return msg

class Twitter:
    """Contains the capability to link images from tweets and other social media"""
    twitter_url_expr = re.compile(r'https?://(?:www\.)?twitter\.com/\S+/status/\d+')
    tweet_selector = 'div.tweet.permalink-tweet'
    twitter_img_selector = 'img[data-aria-label-part]'

    pixiv_url_expr =  re.compile(r'https?://(?:www\.)?pixiv\.net/member_illust\.php\?[\w]+=[\w]+(?:&[\w]+=[\w]+)*')

    hiccears_url_expr = re.compile(r'https?://(?:www\.)?hiccears\.com/(?:(?:gallery)|(?:picture))\.php\?[gp]id=\d+')
    hiccears_link_selector = ".//div[contains(@class, 'row')]//a"
    hiccears_img_selector = ".//a[contains(@href, 'imgs')]"

    tumblr_url_expr = re.compile(r'https?://[\w-]+\.tumblr\.com/post/\d+')
    tumblr_img_selector = ".//meta[@property='og:image']"

    mastodon_url_expr = re.compile(r'https?://\S+/\d+/?(?:$|\s)')
    mastodon_url_groups = re.compile(r'https?://(\S+)(?:/.+)+/(\d+)')
    mastodon_api_fmt = 'https://{}/api/v1/statuses/{}'

    def __init__(self, bot):
        self.bot = bot
        self.headers = {'User-Agent':
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:60.0) '
                        'Gecko/20100101 Firefox/60.0'}
        with open('config/headers.yaml') as fp:
            data = yaml.load(fp)
        self.headers.update(data)
        self.session = aiohttp.ClientSession(loop=bot.loop)
        self.parser = etree.HTMLParser()
        names = (name.partition('_')[0] for name in vars(type(self)) if name.endswith('url_expr'))
        self.expr_dict = {getattr(self, f'{name}_url_expr'): getattr(self, f'display_{name}_images')
                          for name in names}
        self.record = defaultdict(list)
        self.arsenic_session = None
        self.ready = asyncio.Event()
        self.login_task = self.bot.loop.create_task(self.pixiv_login_loop())

    async def __init(self):
        await self.bot.wait_until_ready()
        if not self.bot.user.bot:
            self.bot.unload_extension(__name__)
        else:
            service = Geckodriver(binary='geckodriver', log_file=None)
            browser = Firefox(**{'moz:firefoxOptions': {'args': ['-headless']}})
            self.arsenic_session = await arsenic.start_session(service, browser)
            self.get_session = self._get_context_manager()
            self.ready.set()

    async def pixiv_login_loop(self):
        url = 'https://oauth.secure.pixiv.net/auth/token'
        while True:
            with open('config/logins.yaml') as fp:
                login = yaml.load(fp)
            data = {
                'get_secure_url': 1,
                'client_id': 'MOBrBDS8blbauoSck0ZfDbtuzpyT',
                'client_secret': 'lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj',
            }
            token = login.get('refresh_token')
            if token is not None:
                data['grant_type'] = 'refresh_token'
                data['refresh_token'] = token
            else:
                data['grant_type'] = 'password'
                data['username'] = login['username']
                data['password'] = login['password']
    
            async with self.session.post(url, data=data) as resp:
                res = (await resp.json())['response']
            self.headers['Authorization'] = f'Bearer {res["access_token"]}'
            login['refresh_token'] = res['refresh_token']
            with open('config/logins.yaml', 'w') as fp:
                yaml.dump(login, stream=fp)
            await asyncio.sleep(res['expires_in'])            

    def __unload(self):
        if self.arsenic_session is not None:
            self.bot.loop.create_task(arsenic.stop_session(self.arsenic_session))
        self.bot.loop.create_task(self.session.close())

    def _get_context_manager(self):
        session = self.arsenic_session
        class get_session(asyncio.Lock):
            def __init__(self, link, headers=None):
                super().__init__()
                self.link = link
        
            async def __aenter__(self):
                await super().__aenter__()
                await session.get(self.link)
                session.release = self.release
                return session

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                await super().__aexit__(exc_type, exc_val, exc_tb)

        return get_session
                
    def get(self, *args, **kwargs):
        kwargs['headers'] = {**self.headers, **kwargs.get('headers', {})}
        return _get(self.session, *args, **kwargs)

    async def save(self, img_url, headers=None):
        headers = headers or {}
        headers = {**self.headers, **headers}
        img = BytesIO()
        async with self.get(img_url, headers=headers) as img_resp:
            async for chunk in img_resp.content.iter_any():
                if not chunk:
                    break
                img.write(chunk)
        img.seek(0)
        return img

    async def on_message(self, message):
        guild = message.guild
        if guild is None or message.author.bot:
            return
        if not (await self.bot.config.get(guild.id)).get('twitter'):
            return
        if 'http' not in message.content:
            return

        if self.arsenic_session is None:
            self.arsenic_session = object()
            await self.__init()
        else:
            await self.ready.wait()
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

    async def send(self, ctx, link):
        mode = (await ctx.bot.config.get(ctx.guild.id)).get('twitter')
        if mode == 1:
            await ctx.send(link)
        elif mode == 2:
            img = await self.save(link)
            filename = re.findall(r'\w+\.\w+', link)[-1]
            file = File(img, filename)
            await ctx.send(file=file)
        else:
            raise RuntimeError('Invalid twitter mode!')

    async def display_twitter_images(self, link, ctx):
        async with self.get_session(link) as sess:
            try:
                tweet = await sess.wait_for_element(60, self.tweet_selector)
            except ArsenicTimeout:
                return

            mode = (await ctx.bot.config.get(ctx.guild.id)).get('twitter')
            idx = 1 if mode == 1 else 0
            for img in (await tweet.get_elements(self.twitter_img_selector))[idx:]:
                url = await img.get_attribute('src')
                await self.send(ctx, f'{url}:orig')

    async def display_pixiv_images(self, link, ctx):
        mode = (await ctx.bot.config.get(ctx.guild.id)).get('twitter')
        if 'mode' in link:
            link = re.sub('(?<=mode=)\w+', 'medium', link)
        else:
            link = f'{link}&mode=medium'
        link = link.replace('http://', 'https://')
        illust_id = re.search('illust_id=(\d+)', link).groups()[0]
        headers = {
            'App-OS': 'ios',
            'App-OS-Version': '10.3.1',
            'App-Version': '6.7.1',
            'User-Agent': 'PixivIOSApp/6.7.1 (ios 10.3.1; iPhone8,1)',
            'Authorization': self.headers['Authorization'],
        }
        params = {'illust_id': illust_id}
        url = 'https://app-api.pixiv.net/v1/illust/detail'
        async with self.session.get(url, params=params, headers=headers) as resp:
            res = await resp.json()
        res = res['illust']
        single = res['meta_single_page']
        multi = res['meta_pages']
        if single:
            img_url = single['original_image_url']
            if 'ugoira' in img_url:
                try:
                    file = await self.get_ugoira(link)
                except ResponseError:
                    await ctx.send('Ugoira machine :b:roke')
                    return
            else:
                headers['referer'] = link
                img = await self.save(img_url, headers)
            file = File(img, img_url.rpartition('/')[-1])
            await ctx.send(file=file)
        elif multi:
            # multi_image_post        
            urls = (page['image_urls']['original'] for page in multi)
            num_pages = len(multi)
            if mode == 1:
                r = range(4)
            else:
                r = range(num_pages)
            for img_url, i in zip(urls, r):
                fullsize_url = f'https://pixiv.net/member_illust.php?mode=manga_big&illust_id={illust_id}&page={i}'
                headers['referer'] = fullsize_url
                img = await self.save(img_url, headers)
                file = File(img, img_url.rpartition('/')[-1])
                await ctx.send(file=file)
            remaining = num_pages - 4
            
            if mode == 1 and remaining > 0:
                s = 's' if remaining > 1 else ''
                message = f'{remaining} more image{s} at <{link.replace("medium", "manga")}>'
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
        img = await self.save(url)
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
            await self.send(ctx, url)
            return
        
        images = root.xpath(self.hiccears_link_selector)
        mode = (await ctx.bot.config.get(ctx.guild.id)).get('twitter')
        num = len(images) - 4
        if mode == 1:
            images = images[:4]
        for image in images:
            href = image.get('href')
            url = f'https://{resp.host}{href[1:]}'
            async with self.get(url) as page_resp:
                page = etree.fromstring(await page_resp.read(), self.parser)
            a = page.xpath(self.hiccears_img_selector)[0]
            href = a.get('href')[1:]  # trim leading '.'
            url = f'https://{resp.host}{href}'
            await self.send(ctx, url)
        if mode == 1 and num > 0:
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
        mode = (await ctx.bot.config.get(ctx.guild.id)).get('twitter')
        if mode == 1:
            images = images[idx:4]
            
        for image in images:
            url = image.get('content')
            await self.send(ctx, url)
        num = len(images) - 4
        if mode == 1 and num > 0:
            s = 's' if num > 1 else ''
            message = f'{num} more image{s} at <{link}>'
            await ctx.send(message)

    async def display_mastodon_images(self, link, ctx):
        match = self.mastodon_url_groups.match(link)
        if match is None:
            return
        api_url = self.mastodon_api_fmt.format(*match.groups())
        async with self.session.get(api_url) as resp:
            try:
                post = await resp.json()
            except:
                return

        mode = (await ctx.bot.config.get(ctx.guild.id)).get('twitter')
        idx = 0 if mode != 1 or post['sensitive'] else 1

        for image in post['media_attachments'][idx:]:
            url = image['remote_url'] or image['url']
            await self.send(ctx, url)

        

    @commands.command()
    @is_owner_or(manage_guild=True)
    async def twitter(self, ctx, enabled: Union[bool, str]=True):
        """Change settings for sending images from Twitter and other social media platforms.

        off: do nothing
        on: send links to images that aren't previewed by Discord
        save: upload all images to the channel"""
        if isinstance(enabled, bool):
            await self.bot.config.set(ctx.guild.id, twitter=int(enabled))
            fmt = 'en' if enabled else 'dis'
            await ctx.send(f'Sending Twitter images {fmt}abled.')
        elif enabled in ('save', 'upload'):
            await self.bot.config.set(ctx.guild.id, twitter=2)
            await ctx.send('Twitter images will be directly uploaded.')
        else:
            raise commands.BadArgument(enabled)



def setup(bot):
    bot.add_cog(Twitter(bot))
