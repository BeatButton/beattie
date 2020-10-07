from __future__ import annotations

import asyncio
import re
from asyncio import subprocess
from collections import defaultdict
from datetime import datetime
from hashlib import md5
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import IO, Any, Optional, TypeVar, Union, overload
from zipfile import ZipFile

import aiohttp
import discord
import toml
from discord import AllowedMentions, Embed, File, Message
from discord.ext import commands
from discord.ext.commands import Cog
from lxml import etree

from bot import BeattieBot
from context import BContext
from utils.checks import is_owner_or
from utils.contextmanagers import get as get_
from utils.etc import display_bytes, remove_spoilers
from utils.exceptions import ResponseError

ChannelID = int
MessageID = int
_IO = TypeVar("_IO", bound=IO[bytes])

TWITTER_URL_EXPR = re.compile(
    r"https?://(?:(?:www|mobile|m)\.)?(twitter\.com/[^\s/]+/status/\d+)"
)
TWEET_SELECTOR = ".//div[contains(@class, 'permalink-tweet')]"
TWITTER_IMG_SELECTOR = ".//img[@data-aria-label-part]"
TWITTER_IS_GIF = ".//div[contains(@class, 'PlayableMedia--gif')]"

PIXIV_URL_EXPR = re.compile(
    r"https?://(?:www\.)?pixiv\.net/(?:member_illust\.php\?"
    r"[\w]+=[\w]+(?:&[\w]+=[\w]+)*|(?:\w{2}/)?artworks/\d+(?:#\w*)?)"
)

HICCEARS_URL_EXPR = re.compile(
    r"https?://(?:www\.)?hiccears\.com/(?:(?:gallery)|(?:picture))\.php\?[gp]id=\d+"
)
HICCEARS_IMG_SELECTOR = ".//a[contains(@href, 'imgs')]"
HICCEARS_THUMB_SELECTOR = ".//img[contains(@src, 'thumbnails')]"

TUMBLR_URL_EXPR = re.compile(r"https?://[\w-]+\.tumblr\.com/post/\d+")
TUMBLR_IMG_SELECTOR = ".//meta[@property='og:image']"

MASTODON_URL_EXPR = re.compile(r"https?://\S+/\w+/?(?:>|$|\s)")
MASTODON_URL_GROUPS = re.compile(r"https?://([^\s/]+)(?:/.+)+/(\w+)")
MASTODON_API_FMT = "https://{}/api/v1/statuses/{}"

INKBUNNY_URL_EXPR = re.compile(
    r"https?://(?:www\.)?inkbunny\.net/s/(\d+)(?:-p\d+-)?(?:#.*)?"
)
INKBUNNY_API_FMT = "https://inkbunny.net/api_{}.php"

IMGUR_URL_EXPR = re.compile(r"https?://(?:www\.)?imgur\.com/(?:a|gallery)/(\w+)")


class CrosspostContext(BContext):
    cog: Crosspost

    async def send(
        self,
        content: Optional[object] = None,
        *,
        tts: bool = False,
        embed: Optional[Embed] = None,
        file: Optional[File] = None,
        files: Optional[list[File]] = None,
        delete_after: Optional[float] = None,
        nonce: Optional[int] = None,
        allowed_mentions: Optional[AllowedMentions] = None,
    ) -> Message:
        if file:
            fp = file.fp
            assert isinstance(fp, BytesIO)
            guild = self.guild
            assert guild is not None
            size = len(fp.getbuffer())
            if size >= guild.filesize_limit:
                content = f"Image too large to upload ({display_bytes(size)})."
                file = None
        msg = await super().send(
            content,
            tts=tts,
            embed=embed,
            file=file,
            files=files,
            delete_after=delete_after,
            nonce=nonce,
            allowed_mentions=allowed_mentions,
        )
        self.cog.sent_images[self.message.id].append((msg.channel.id, msg.id))
        return msg


class Crosspost(Cog):
    """Crossposts images from tweets and other social media"""

    bot: BeattieBot

    hiccears_headers: dict[str, str] = {}
    imgur_headers: dict[str, str] = {}
    pixiv_headers: dict[str, str] = {
        "App-OS": "ios",
        "App-OS-Version": "10.3.1",
        "App-Version": "6.7.1",
        "User-Agent": "PixivIOSApp/6.7.1 (ios 10.3.1; iPhone8,1)",
    }
    inkbunny_sid: str = ""

    sent_images: dict[MessageID, list[tuple[ChannelID, MessageID]]]
    ongoing_tasks: dict[MessageID, asyncio.Task]

    def __init__(self, bot: BeattieBot):
        self.bot = bot
        with open("config/headers.toml") as fp:
            self.headers = toml.load(fp)
        self.session = aiohttp.ClientSession(loop=bot.loop)
        self.parser = etree.HTMLParser()
        self.expr_dict = {
            expr: getattr(self, f"display_{name.partition('_')[0].lower()}_images")
            for name, expr in globals().items()
            if name.endswith("URL_EXPR")
        }
        self.sent_images = defaultdict(list)
        self.ongoing_tasks = {}
        self.login_task = self.bot.loop.create_task(self.pixiv_login_loop())
        self.init_task = bot.loop.create_task(self.__init())

    async def __init(self) -> None:
        with open("config/logins.toml") as fp:
            data = toml.load(fp)

        imgur_id = data["imgur"]["id"]
        self.imgur_headers["Authorization"] = f"Client-ID {imgur_id}"

        self.hiccears_headers = data["hiccears"]

        ib_login = data["inkbunny"]

        url = INKBUNNY_API_FMT.format("login")
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

            while True:
                try:
                    async with self.get(
                        url,
                        "POST",
                        data=data,
                        use_default_headers=False,
                        headers=headers,
                    ) as resp:
                        res = (await resp.json())["response"]
                except Exception as e:
                    message = "An error occurred in the pixiv login loop"
                    self.bot.logger.exception(
                        message, exc_info=(type(e), e, e.__traceback__)
                    )
                else:
                    break

            self.pixiv_headers["Authorization"] = f'Bearer {res["access_token"]}'
            login["refresh_token"] = res["refresh_token"]
            with open("config/logins.toml", "w") as fp:
                toml.dump(logins, fp)
            await asyncio.sleep(res["expires_in"])

    def cog_unload(self) -> None:
        self.bot.loop.create_task(self.session.close())
        self.login_task.cancel()

    def get(
        self,
        url: str,
        method: str = "GET",
        *,
        use_default_headers: bool = True,
        **kwargs: Any,
    ) -> get_:
        if use_default_headers:
            kwargs["headers"] = {**self.headers, **kwargs.get("headers", {})}
        return get_(self.session, url, method, **kwargs)

    @overload
    async def save(
        self,
        img_url: str,
        *,
        fp: None = ...,
        seek_begin: bool = ...,
        use_default_headers: bool = ...,
        headers: Optional[dict[str, str]] = ...,
    ) -> BytesIO:
        ...

    @overload
    async def save(
        self,
        img_url: str,
        *,
        fp: _IO,
        seek_begin: bool = ...,
        use_default_headers: bool = ...,
        headers: Optional[dict[str, str]] = ...,
    ) -> _IO:
        ...

    async def save(
        self,
        img_url: str,
        *,
        fp=None,
        seek_begin: bool = True,
        use_default_headers: bool = True,
        headers: Optional[dict[str, str]] = None,
    ):
        headers = headers or {}
        img = fp or BytesIO()
        async with self.get(
            img_url, use_default_headers=use_default_headers, headers=headers
        ) as img_resp:
            async for chunk in img_resp.content.iter_any():
                if not chunk:
                    break
                img.write(chunk)
        if seek_begin:
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
        channel = message.channel
        assert isinstance(channel, discord.TextChannel)
        if not guild.me.permissions_in(channel).send_messages:
            return
        if not (await self.bot.config.get_guild(guild.id)).get("crosspost_enabled"):
            return
        if "http" not in message.content:
            return

        ctx = await self.bot.get_context(message, cls=CrosspostContext)
        if ctx.command is None:
            ctx.command = self.post
            task = asyncio.create_task(self.process_links(ctx))
            self.ongoing_tasks[message.id] = task
            try:
                await asyncio.wait_for(task, None)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                raise e
            finally:
                del self.ongoing_tasks[message.id]

    @Cog.listener()
    async def on_raw_message_delete(
        self, payload: discord.RawMessageDeleteEvent
    ) -> None:
        message_id = payload.message_id
        if task := self.ongoing_tasks.get(message_id):
            task.cancel()
            await asyncio.sleep(0)
        if messages := self.sent_images.pop(message_id, None):
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
        headers: Optional[dict[str, str]] = None,
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
        guild = ctx.guild
        assert guild is not None
        return (await ctx.bot.config.get_guild(guild.id)).get("crosspost_mode") or 1

    async def get_max_pages(self, ctx: BContext) -> int:
        guild = ctx.guild
        assert guild is not None

        max_pages = (await ctx.bot.config.get_guild(guild.id)).get(
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
            tweet = root.xpath(TWEET_SELECTOR)[0]
        except IndexError:
            await ctx.send("Failed to get tweet. Maybe the account is locked?")
            return

        if imgs := tweet.xpath(TWITTER_IMG_SELECTOR):
            for img in imgs:
                url = img.get("src")
                await self.send(ctx, f"{url}:orig")
        elif tweet.xpath(TWITTER_IS_GIF):
            proc = await subprocess.create_subprocess_shell(
                f"youtube-dl {link} -o - | "
                "ffmpeg -i pipe:0 "
                "-vf 'split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse,loop=-1' "
                "-f gif pipe:1",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            gif = BytesIO()
            tweet_id = link.rpartition("/")[2].partition("?")[0]
            filename = f"{tweet_id}.gif"

            stdout, _stderr = await proc.communicate()

            gif.write(stdout)
            gif.seek(0)

            file = File(gif, filename)

            await ctx.send(file=file)

    async def display_pixiv_images(self, link: str, ctx: CrosspostContext) -> None:
        if "mode" in link:
            link = re.sub(r"(?<=mode=)\w+", "medium", link)
        elif "illust_id" in link:
            link = f"{link}&mode=medium"
        link = link.replace("http://", "https://")
        if match := re.search(r"(?:illust_id=|artworks/)(\d+)", link):
            illust_id = match.group(1)
        else:
            await ctx.send("Failed to find illust ID in pixiv link. This is a bug.")
            return
        params = {"illust_id": illust_id}
        url = "https://app-api.pixiv.net/v1/illust/detail"
        async with self.get(
            url, params=params, use_default_headers=False, headers=self.pixiv_headers
        ) as resp:
            res = await resp.json()
        try:
            res = res["illust"]
        except KeyError:
            await ctx.send(
                "This feature works sometimes, but isn't working right now!"
                f"\nDebug info:\n{res.get('error')}"
            )
            return

        headers = {**self.pixiv_headers, "referer": link}
        guild = ctx.guild
        assert guild is not None
        filesize_limit = guild.filesize_limit
        content: Optional[str]

        if single := res["meta_single_page"]:
            img_url = single["original_image_url"]
            if "ugoira" in img_url:
                content = None
                file = await self.get_ugoira(illust_id)
            else:
                content, file = await self.save_pixiv(img_url, headers, filesize_limit)
            await ctx.send(content, file=file)
        elif multi := res["meta_pages"]:
            # multi_image_post
            urls = (page["image_urls"]["original"] for page in multi)

            max_pages = await self.get_max_pages(ctx)
            num_pages = len(multi)

            if max_pages == 0:
                max_pages = num_pages

            tasks = [
                self.bot.loop.create_task(
                    self.save_pixiv(img_url, headers, filesize_limit)
                )
                for img_url, _ in zip(urls, range(max_pages))
            ]

            for task in tasks:
                content, file = await task
                await ctx.send(content, file=file)

            remaining = num_pages - max_pages

            if remaining > 0:
                s = "s" if remaining > 1 else ""
                message = (
                    f"{remaining} more image{s} at "
                    f"<https://www.pixiv.net/en/artworks/{illust_id}>"
                )
                await ctx.send(message)

    async def save_pixiv(
        self, img_url: str, headers: dict[str, str], filesize_limit: int
    ) -> tuple[Optional[str], File]:
        content = None
        img = await self.save(img_url, headers=headers)
        if len(img.getbuffer()) > filesize_limit:
            img_url = img_url.replace("img-original", "img-master")
            head, _, ext = img_url.rpartition(".")
            img_url = f"{head}_master1200.{ext}"
            img = await self.save(img_url, headers=headers)
            content = "Full size too large, standard resolution used."
        file = File(img, img_url.rpartition("/")[-1])
        return content, file

    async def get_ugoira(self, illust_id: str) -> File:
        url = "https://app-api.pixiv.net/v1/ugoira/metadata"
        params = {"illust_id": illust_id}
        headers = self.pixiv_headers
        async with self.get(
            url, params=params, use_default_headers=False, headers=headers
        ) as resp:
            res = (await resp.json())["ugoira_metadata"]

        zip_url = res["zip_urls"]["medium"]
        zip_url = re.sub(r"ugoira\d+x\d+", "ugoira1920x1080", zip_url)

        headers = {
            **self.pixiv_headers,
            "referer": f"https://www.pixiv.net/en/artworks/{illust_id}",
        }

        zip_bytes = await self.save(zip_url, headers=headers, use_default_headers=False)
        zfp = ZipFile(zip_bytes)

        with TemporaryDirectory() as td:
            tempdir = Path(td)
            zfp.extractall(tempdir)
            with open(tempdir / "durations.txt", "w") as fp:
                for frame in res["frames"]:
                    duration = int(frame["delay"]) / 1000
                    fp.write(f"file '{frame['file']}'\nduration {duration}\n")

            proc = await subprocess.create_subprocess_exec(
                "ffmpeg",
                "-i",
                f"{tempdir}/%06d.jpg",
                "-vf",
                "palettegen",
                f"{tempdir}/palette.png",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            await proc.wait()

            proc = await subprocess.create_subprocess_exec(
                "ffmpeg",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                f"{tempdir}/durations.txt",
                "-i",
                f"{tempdir}/palette.png",
                "-lavfi",
                "paletteuse",
                "-f",
                "gif",
                "pipe:1",
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )

            stdout, _stderr = await proc.communicate()

        img = BytesIO(stdout)
        img.seek(0)
        name = f"{illust_id}.gif"
        return File(img, name)

    async def display_hiccears_images(self, link: str, ctx: CrosspostContext) -> None:
        async with self.get(link, headers=self.hiccears_headers) as resp:
            root = etree.fromstring(await resp.read(), self.parser)

        if single_image := root.xpath(HICCEARS_IMG_SELECTOR):
            a = single_image[0]
            href = a.get("href").lstrip(".")
            url = f"https://{resp.host}{href}"
            await self.send(ctx, url)
            return

        thumbs = root.xpath(HICCEARS_THUMB_SELECTOR)

        num_images = len(thumbs)

        if num_images == 0:
            await ctx.send(
                "Hiccears login expired. <@!140293604726800385> needs to fix this. >:("
            )
            return

        max_pages = await self.get_max_pages(ctx)

        if max_pages == 0:
            max_pages = num_images

        pages_remaining = num_images - max_pages
        for thumb in thumbs[:max_pages]:
            href = thumb.get("src").lstrip(".").replace("thumbnails", "imgs")
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
        images = root.xpath(TUMBLR_IMG_SELECTOR)
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
        if (match := MASTODON_URL_GROUPS.match(link)) is None:
            return
        api_url = MASTODON_API_FMT.format(*match.groups())
        try:
            async with self.get(api_url, use_default_headers=False) as resp:
                post = await resp.json()
        except (ResponseError, aiohttp.ClientError):
            return

        if not (images := post.get("media_attachments")):
            return

        mode = await self.get_mode(ctx)

        idx = 0 if mode != 1 or post["sensitive"] else 1

        for image in images[idx:]:
            url = image["remote_url"] or image["url"]
            if image.get("type") == "gifv":
                with NamedTemporaryFile() as fp:
                    await self.save(
                        url, fp=fp, seek_begin=False, use_default_headers=False
                    )
                    proc = await asyncio.create_subprocess_exec(
                        "ffmpeg",
                        "-i",
                        fp.name,
                        "-vf",
                        "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse,loop=-1",
                        "-f",
                        "gif",
                        "pipe:1",
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                    )

                    stdout, _stderr = await proc.communicate()
                img = BytesIO(stdout)

                filename = f"{url.rpartition('/')[2]}.gif"
                file = File(img, filename)
                await ctx.send(file=file)
            else:
                await self.send(ctx, url)

    async def display_inkbunny_images(self, sub_id: str, ctx: CrosspostContext) -> None:
        url = INKBUNNY_API_FMT.format("submissions")
        params = {"sid": self.inkbunny_sid, "submission_ids": sub_id}
        async with self.get(
            url, "POST", use_default_headers=False, params=params
        ) as resp:
            response = await resp.json()

        sub = response["submissions"][0]

        for file in sub["files"]:
            url = file["file_url_full"]
            await self.send(ctx, url)

    async def display_imgur_images(self, album_id: str, ctx: CrosspostContext) -> None:
        async with self.get(
            f"https://api.imgur.com/3/album/{album_id}",
            use_default_headers=False,
            headers=self.imgur_headers,
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
            "This command is deprecated! "
            f"Please use `{ctx.prefix}crosspost` to manage settings."
        )

    @commands.group()
    @is_owner_or(manage_guild=True)
    async def crosspost(self, ctx: BContext) -> None:
        """Change image crosspost settings"""
        pass

    @crosspost.command()
    async def auto(self, ctx: BContext, enabled: bool) -> None:
        """Enable or disable automatic crossposting"""
        guild = ctx.guild
        assert guild is not None
        await self.bot.config.set_guild(guild.id, crosspost_enabled=enabled)
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

        guild = ctx.guild
        assert guild is not None
        await self.bot.config.set_guild(guild.id, crosspost_mode=crosspost_mode)
        await ctx.send("Crosspost mode updated.")

    @crosspost.command()
    async def pages(self, ctx: BContext, max_pages: int) -> None:
        """Set the maximum number of images to send.

        Set to 0 for no limit."""
        guild = ctx.guild
        assert guild is not None
        await self.bot.config.set_guild(guild.id, crosspost_max_pages=max_pages)
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
