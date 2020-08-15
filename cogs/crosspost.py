from __future__ import annotations  # type: ignore

import asyncio
import json
import re
import traceback
from collections import defaultdict
from datetime import datetime
from hashlib import md5
from io import BytesIO, StringIO
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import aiohttp
import discord
import toml
from discord import File, Guild, HTTPException, Message
from discord.ext import commands
from discord.ext.commands import Bot, Cog
from lxml import etree

from bot import BeattieBot
from context import BContext
from utils.checks import is_owner_or
from utils.contextmanagers import get as get_
from utils.etc import remove_spoilers
from utils.exceptions import ResponseError

ChannelID = int
MessageID = int


class CrosspostContext(BContext):
    cog: Crosspost

    async def send(self, *args: Any, **kwargs: Any) -> Message:
        file: File
        if file := kwargs.get("file"):  # type: ignore
            fp: BytesIO = file.fp  # type: ignore
            guild = self.guild
            assert isinstance(guild, Guild)
            if len(fp.getbuffer()) >= guild.filesize_limit:
                args = ("Image too large to upload.",)
                kwargs = {}
        msg = await super().send(*args, **kwargs)
        self.cog.sent_images[self.message.id].append((msg.channel.id, msg.id))
        return msg


class Crosspost(Cog):
    """Crossposts images from tweets and other social media"""

    bot: BeattieBot

    twitter_url_expr = re.compile(
        r"https?://(?:(?:www|mobile|m)\.)?(twitter\.com/\S+/status/\d+)"
    )
    tweet_selector = ".//div[contains(@class, 'permalink-tweet')]"
    twitter_img_selector = ".//img[@data-aria-label-part]"

    pixiv_url_expr = re.compile(
        r"https?://(?:www\.)?pixiv\.net/(?:member_illust\.php\?[\w]+=[\w]+(?:&[\w]+=[\w]+)*|(?:\w{2}/)?artworks/\d+(?:#\w*)?)"
    )

    hiccears_url_expr = re.compile(
        r"https?://(?:www\.)?hiccears\.com/(?:(?:gallery)|(?:picture))\.php\?[gp]id=\d+"
    )
    hiccears_link_selector = ".//div[contains(@class, 'row')]//a"
    hiccears_img_selector = ".//a[contains(@href, 'imgs')]"
    hiccears_headers: Dict[str, str] = {}

    tumblr_url_expr = re.compile(r"https?://[\w-]+\.tumblr\.com/post/\d+")
    tumblr_img_selector = ".//meta[@property='og:image']"

    mastodon_url_expr = re.compile(r"https?://\S+/\w+/?(?:>|$|\s)")
    mastodon_url_groups = re.compile(r"https?://([^\s/]+)(?:/.+)+/(\w+)")
    mastodon_api_fmt = "https://{}/api/v1/statuses/{}"

    inkbunny_url_expr = re.compile(r"https?://inkbunny\.net/s/(\d+)(?:-p\d+-)?(?:#.*)?")
    inkbunny_api_fmt = "https://inkbunny.net/api_{}.php"
    inkbunny_sid = ""

    imgur_url_expr = re.compile(r"https?://(?:www\.)?imgur\.com/(?:a|gallery)/(\w+)")
    imgur_headers: Dict[str, str] = {}

    sent_images: Dict[int, List[Tuple[ChannelID, MessageID]]]

    def __init__(self, bot: BeattieBot):
        self.bot = bot
        with open("config/headers.toml") as fp:
            self.headers = toml.load(fp)
        self.session = aiohttp.ClientSession(loop=bot.loop)
        self.parser = etree.HTMLParser()
        names = (
            name.partition("_")[0]
            for name in vars(type(self))
            if name.endswith("url_expr")
        )
        self.expr_dict = {
            getattr(self, f"{name}_url_expr"): getattr(self, f"display_{name}_images")
            for name in names
        }
        self.sent_images = defaultdict(list)
        self.login_task = self.bot.loop.create_task(self.pixiv_login_loop())
        self.init_task = bot.loop.create_task(self.__init())

    async def __init(self) -> None:
        with open("config/logins.toml") as fp:
            data = toml.load(fp)

        imgur_id = data["imgur"]["id"]
        self.imgur_headers["Authorization"] = f"Client-ID {imgur_id}"

        self.hiccears_headers = data["hiccears"]

        ib_login = data["inkbunny"]

        url = self.inkbunny_api_fmt.format("login")
        async with self.get(url, "POST", params=ib_login) as resp:
            json = await resp.json()
            self.inkbunny_sid = json["sid"]

    def cog_check(self, ctx: BContext) -> bool:
        return ctx.guild is not None

    async def pixiv_login_loop(self) -> None:
        url = "https://oauth.secure.pixiv.net/auth/token"
        while True:
            with open("config/logins.toml") as fp:
                logins = toml.load(fp)
            login = logins["pixiv"]
            data = {
                "get_secure_url": 1,
                "client_id": "MOBrBDS8blbauoSck0ZfDbtuzpyT",
                "client_secret": "lsACyCD94FhDUtGTXi3QzcFE2uU1hqtDaKeqrdwj",
            }

            if (token := login.get("refresh_token")) is not None:
                data["grant_type"] = "refresh_token"
                data["refresh_token"] = token
            else:
                data["grant_type"] = "password"
                data["username"] = login["username"]
                data["password"] = login["password"]

            hash_secret = (
                "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
            )

            now = datetime.now().isoformat()
            headers = {
                "X-Client-Time": now,
                "X-Client-Hash": md5((now + hash_secret).encode("utf-8")).hexdigest(),
            }

            async with self.session.post(url, data=data, headers=headers) as resp:
                res = (await resp.json())["response"]

            self.headers["Authorization"] = f'Bearer {res["access_token"]}'
            login["refresh_token"] = res["refresh_token"]
            with open("config/logins.toml", "w") as fp:
                toml.dump(logins, fp)
            await asyncio.sleep(res["expires_in"])

    def cog_unload(self) -> None:
        self.bot.loop.create_task(self.session.close())
        self.login_task.cancel()

    def get(self, url: str, method: str = "GET", **kwargs: Any) -> get_:
        kwargs["headers"] = {**self.headers, **kwargs.get("headers", {})}
        return get_(self.session, url, method, **kwargs)

    async def save(
        self,
        img_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        use_default_headers: bool = True,
    ) -> BytesIO:
        headers = headers or {}
        if use_default_headers:
            headers = {**self.headers, **headers}
        img = BytesIO()
        async with self.get(img_url, headers=headers) as img_resp:
            async for chunk in img_resp.content.iter_any():
                if not chunk:
                    break
                img.write(chunk)
        img.seek(0)
        return img

    async def process_links(self, ctx: CrosspostContext) -> None:
        content = remove_spoilers(ctx.message.content)
        for expr, func in self.expr_dict.items():
            for link in expr.findall(content):
                try:
                    await func(link, ctx)
                except ResponseError as e:
                    if e.code == 404:
                        await ctx.send("Post not found.")
                    else:
                        await ctx.bot.handle_error(ctx, e)
                except Exception as e:
                    await ctx.bot.handle_error(ctx, e)

    @Cog.listener()
    async def on_message(self, message: Message) -> None:
        if (guild := message.guild) is None or message.author.bot:
            return
        if not guild.me.permissions_in(message.channel).send_messages:  # type: ignore
            return
        if not (await self.bot.config.get_guild(guild.id)).get("crosspost_enabled"):
            return
        if "http" not in message.content:
            return

        ctx = await self.bot.get_context(message, cls=CrosspostContext)
        if ctx.command is None:
            ctx.command = self.post
            await self.process_links(ctx)

    @Cog.listener()
    async def on_raw_message_delete(
        self, payload: discord.RawMessageDeleteEvent
    ) -> None:
        message_id = payload.message_id
        messages = self.sent_images.pop(message_id, None)
        if messages is not None:
            for channel_id, message_id in messages:
                try:
                    await self.bot.http.delete_message(channel_id, message_id)
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    return

    async def send(
        self,
        ctx: CrosspostContext,
        link: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        use_default_headers: bool = True,
    ) -> None:
        mode = await self.get_mode(ctx)
        if mode == 1:
            await ctx.send(link)
        elif mode == 2:
            img = await self.save(
                link, headers=headers, use_default_headers=use_default_headers
            )
            filename = re.findall(r"[\w. -]+\.[\w. -]+", link)[-1]
            file = File(img, filename)
            await ctx.send(file=file)
        else:
            raise RuntimeError("Invalid crosspost mode!")

    async def get_mode(self, ctx: BContext) -> int:
        if ctx.guild is None:
            return 1
        return (await ctx.bot.config.get_guild(ctx.guild.id)).get("crosspost_mode") or 1

    async def get_max_pages(self, ctx: BContext) -> int:
        if ctx.guild is None:
            return 4

        max_pages = (await ctx.bot.config.get_guild(ctx.guild.id)).get(
            "crosspost_max_pages"
        )
        if max_pages is None:
            mode = await self.get_mode(ctx)
            if mode == 1:
                max_pages = 4
            else:
                max_pages = 0
        return max_pages

    async def display_twitter_images(self, link: str, ctx: CrosspostContext) -> None:
        if await self.get_mode(ctx) == 1:
            return

        link = f"https://{link}"

        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)

        try:
            tweet = root.xpath(self.tweet_selector)[0]
        except IndexError:
            await ctx.send("Failed to get tweet. Maybe the account is locked?")
            return

        for img in tweet.xpath(self.twitter_img_selector):
            url = img.get("src")
            await self.send(ctx, f"{url}:orig")

    async def display_pixiv_images(self, link: str, ctx: CrosspostContext) -> None:
        if "mode" in link:
            link = re.sub(r"(?<=mode=)\w+", "medium", link)
        elif "illust_id" in link:
            link = f"{link}&mode=medium"
        link = link.replace("http://", "https://")
        if match := re.search(r"illust_id=(\d+)|artworks/(\d+)", link):
            illust_id = next(filter(None, match.groups()))
        else:
            await ctx.send("Failed to find illust ID in pixiv link. This is a bug.")
            return
        headers = {
            "App-OS": "ios",
            "App-OS-Version": "10.3.1",
            "App-Version": "6.7.1",
            "User-Agent": "PixivIOSApp/6.7.1 (ios 10.3.1; iPhone8,1)",
            "Authorization": self.headers["Authorization"],
        }
        params = {"illust_id": illust_id}
        url = "https://app-api.pixiv.net/v1/illust/detail"
        async with self.session.get(url, params=params, headers=headers) as resp:
            res = await resp.json()
        try:
            res = res["illust"]
        except KeyError:
            await ctx.send(
                f"This feature works sometimes, but isn't working right now!\nDebug info:\n{res.get('error')}"
            )
            return

        if single := res["meta_single_page"]:
            img_url = single["original_image_url"]
            if "ugoira" in img_url:
                try:
                    file = await self.get_ugoira(link)
                except ResponseError:
                    await ctx.send("Ugoira machine :b:roke")
                    return
            else:
                headers["referer"] = link
                img = await self.save(img_url, headers=headers)
                file = File(img, img_url.rpartition("/")[-1])
            await ctx.send(file=file)
        elif multi := res["meta_pages"]:
            # multi_image_post
            urls = (page["image_urls"]["original"] for page in multi)

            max_pages = await self.get_max_pages(ctx)
            num_pages = len(multi)

            if max_pages == 0:
                max_pages = num_pages

            tasks = []

            for img_url, i in zip(urls, range(max_pages)):
                fullsize_url = f"https://pixiv.net/member_illust.php?mode=manga_big&illust_id={illust_id}&page={i}"
                headers["referer"] = fullsize_url
                task = self.bot.loop.create_task(self.save(img_url, headers=headers))
                filename = img_url.rpartition("/")[-1]
                tasks.append((filename, task))

            for filename, task in tasks:
                img = await task
                file = File(img, filename)
                await ctx.send(file=file)

            remaining = num_pages - max_pages

            if remaining > 0:
                s = "s" if remaining > 1 else ""
                message = f"{remaining} more image{s} at <https://www.pixiv.net/en/artworks/{illust_id}>"
                await ctx.send(message)

    async def get_ugoira(self, link: str, fmt: str = "gif") -> File:
        params = {"url": link, "format": fmt}
        conv_url = "http://ugoira.dataprocessingclub.org/convert"
        async with self.get(conv_url, params=params, timeout=None) as resp:
            text = await resp.text()
        url = json.loads(text)["url"]
        img = await self.save(url)
        name = url.rpartition("/")[2]
        return File(img, name)

    async def display_hiccears_images(self, link: str, ctx: CrosspostContext) -> None:
        async with self.get(link, headers=self.hiccears_headers) as resp:
            root = etree.fromstring(await resp.read(), self.parser)

        if single_image := root.xpath(self.hiccears_img_selector):
            a = single_image[0]
            href = a.get("href").lstrip(".")
            url = f"https://{resp.host}{href}"
            await self.send(ctx, url)
            return

        images = root.xpath(self.hiccears_link_selector)
        max_pages = await self.get_max_pages(ctx)

        num_images = len(images)
        if max_pages == 0:
            max_pages = num_images

        pages_remaining = num_images - max_pages
        images = images[:max_pages]
        for image in images:
            href = image.get("href")
            url = f"https://{resp.host}{href[1:]}"
            async with self.get(url) as page_resp:
                page = etree.fromstring(await page_resp.read(), self.parser)
            try:
                a = page.xpath(self.hiccears_img_selector)[0]
            except IndexError:
                # hit a premium gallery teaser thumbnail
                return
            href = a.get("href")[1:]  # trim leading '.'
            url = f"https://{resp.host}{href}"
            await self.send(ctx, url)
        if pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            message = f"{pages_remaining} more image{s} at <{link}>"
            await ctx.send(message)

    async def display_tumblr_images(self, link: str, ctx: CrosspostContext) -> None:
        idx = 1
        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)
        if not str(resp.url).startswith(link):  # explicit blog redirect
            async with self.bot.session.get(
                link
            ) as resp:  # somehow this doesn't get redirected?
                root = etree.fromstring(await resp.read(), self.parser)
            idx = 0
        images = root.xpath(self.tumblr_img_selector)
        mode = await self.get_mode(ctx)
        max_pages = await self.get_max_pages(ctx)

        num_images = len(images)

        if max_pages == 0:
            max_pages = num_images

        pages_remaining = num_images - max_pages

        images = images[idx:max_pages]

        for image in images:
            url = image.get("content")
            await self.send(ctx, url)
        if mode == 1 and pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            message = f"{pages_remaining} more image{s} at <{link}>"
            await ctx.send(message)

    async def display_mastodon_images(self, link: str, ctx: CrosspostContext) -> None:
        if (match := self.mastodon_url_groups.match(link)) is None:
            return
        api_url = self.mastodon_api_fmt.format(*match.groups())
        try:
            async with self.session.get(api_url) as resp:
                post = await resp.json()
        except (ResponseError, aiohttp.ContentTypeError):
            return

        if not (images := post.get("media_attachments")):
            return

        mode = await self.get_mode(ctx)

        idx = 0 if mode != 1 or post["sensitive"] else 1

        for image in images[idx:]:
            url = image["remote_url"] or image["url"]
            await self.send(ctx, url)

    async def display_inkbunny_images(self, sub_id: str, ctx: CrosspostContext) -> None:
        url = self.inkbunny_api_fmt.format("submissions")
        params = {"sid": self.inkbunny_sid, "submission_ids": sub_id}
        async with self.get(url, "POST", params=params) as resp:
            response = await resp.json()

        sub = response["submissions"][0]

        for file in sub["files"]:
            url = file["file_url_full"]
            await self.send(ctx, url)

    async def display_imgur_images(self, album_id: str, ctx: CrosspostContext) -> None:
        async with self.get(
            f"https://api.imgur.com/3/album/{album_id}", headers=self.imgur_headers
        ) as resp:
            data = await resp.json()

        images = data["data"]["images"]
        urls = (image["link"] for image in data["data"]["images"])

        max_pages = await self.get_max_pages(ctx)
        num_pages = len(images)

        if max_pages == 0:
            max_pages = num_pages

        async def helper(link, n=1):
            try:
                await self.send(
                    ctx, link, headers=self.imgur_headers, use_default_headers=False
                )
            except ResponseError as e:
                if e.code == 400 and n <= 10:
                    await asyncio.sleep(n)
                    await helper(link, n + 1)
                else:
                    raise e

        for img_url, _ in zip(urls, range(max_pages)):
            await helper(img_url)

        remaining = num_pages - max_pages

        if remaining > 0:
            s = "s" if remaining > 1 else ""
            message = f"{remaining} more image{s} at <https://imgur.com/a/{album_id}>"
            await ctx.send(message)

    @commands.command(hidden=True)
    @is_owner_or(manage_guild=True)
    async def twitter(self, ctx: BContext, enabled: Union[bool, str] = True) -> None:
        await ctx.send(
            f"This command is deprecated! Please use `{ctx.prefix}crosspost` to manage settings."
        )

    @commands.group()
    @is_owner_or(manage_guild=True)
    async def crosspost(self, ctx: BContext) -> None:
        """Change image crosspost settings"""
        pass

    @crosspost.command()
    async def auto(self, ctx: BContext, enabled: bool) -> None:
        """Enable or disable automatic crossposting"""
        guild_id = ctx.guild.id  # type: ignore
        await self.bot.config.set_guild(guild_id, crosspost_enabled=enabled)
        fmt = "en" if enabled else "dis"
        await ctx.send(f"Crossposting images {fmt}abled.")

    @crosspost.command()
    async def mode(self, ctx: BContext, mode: str) -> None:
        """Change image crossposting mode
        
        link: send a link to images when available
        upload: always upload image files"""
        if mode == "link":
            crosspost_mode = 1
        elif mode == "upload":
            crosspost_mode = 2
        else:
            raise commands.BadArgument(mode)

        guild_id = ctx.guild.id  # type: ignore
        await self.bot.config.set_guild(guild_id, crosspost_mode=crosspost_mode)
        await ctx.send("Crosspost mode updated.")

    @crosspost.command()
    async def pages(self, ctx: BContext, max_pages: int) -> None:
        """Set the maximum number of images to send.
        
        Set to 0 for no limit."""
        guild_id = ctx.guild.id  # type: ignore
        await self.bot.config.set_guild(guild_id, crosspost_max_pages=max_pages)
        await ctx.send(f"Max crosspost pages set to {max_pages}")

    @commands.command()
    async def post(self, ctx: BContext, *, _: str) -> None:
        """Embed images in the given links regardles of the global embed setting."""
        new_ctx = await self.bot.get_context(ctx.message, cls=CrosspostContext)
        await self.process_links(new_ctx)

    @commands.command(aliases=["_"])
    async def nopost(self, ctx: BContext, *, _: str = "") -> None:
        """Ignore links in the following message.
        
        You can also use ||spoiler tags|| to achieve the same thing."""
        pass


def setup(bot: BeattieBot) -> None:
    bot.add_cog(Crosspost(bot))
