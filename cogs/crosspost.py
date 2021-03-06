from __future__ import annotations

import asyncio
import copy
import re
from asyncio import subprocess
from collections.abc import Awaitable, Callable
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
from discord import AllowedMentions, CategoryChannel, Embed, File, Message, TextChannel
from discord.ext import commands
from discord.ext.commands import BadUnionArgument, ChannelNotFound, Cog
from lxml import etree

from bot import BeattieBot
from context import BContext
from schema.crosspost import Crosspost as CrosspostSettings
from schema.crosspost import Table
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


async def try_wait_for(
    proc: asyncio.subprocess.Process, *, timeout: int = 180, kill_timeout: int = 15
) -> bytes:
    try:
        out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await gently_kill(proc, timeout=kill_timeout)
        raise
    else:
        return out


async def gently_kill(proc: asyncio.subprocess.Process, *, timeout: int):
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()


class Settings:
    __slots__ = ("auto", "mode", "max_pages")

    auto: Optional[bool]
    mode: Optional[int]
    max_pages: Optional[int]

    def __init__(
        self,
        auto: bool = None,
        mode: int = None,
        max_pages: int = None,
    ) -> None:
        self.auto = auto
        self.mode = mode
        self.max_pages = max_pages

    def apply(self, other: Settings) -> Settings:
        """Returns a Settings with own values overwritten by non-None values of other"""
        out = copy.copy(self)
        auto, mode, max_pages = other.auto, other.mode, other.max_pages
        if auto is not None:
            out.auto = auto
        if mode is not None:
            out.mode = mode
        if max_pages is not None:
            out.max_pages = max_pages

        return out

    def asdict(self) -> dict[str, Any]:
        return {k: v for k in self.__slots__ if (v := getattr(self, k)) is not None}


class Config:
    def __init__(self, bot: BeattieBot):
        self.db = bot.db
        self.bot = bot
        self.db.bind_tables(Table)
        bot.loop.create_task(self.__init())
        self._cache: dict[tuple[int, int], Settings] = {}

    async def __init(self) -> None:
        await self.bot.wait_until_ready()
        await CrosspostSettings.create(if_not_exists=True)

    async def get(self, message: Message) -> Settings:
        guild = message.guild
        assert guild is not None
        channel = message.channel
        assert isinstance(channel, TextChannel)

        guild_id = guild.id
        out = await self._get(guild_id, 0)

        if category := channel.category:
            out = out.apply(await self._get(guild_id, category.id))
        out = out.apply(await self._get(guild_id, message.channel.id))

        return out

    async def _get(self, guild_id: int, channel_id: int) -> Settings:
        try:
            return self._cache[(guild_id, channel_id)]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(CrosspostSettings).where(
                    (CrosspostSettings.guild_id == guild_id)
                    & (CrosspostSettings.channel_id == channel_id)
                )
                config = await query.first()
            if config is None:
                res = Settings()
            else:
                res = Settings(config.auto, config.mode, config.max_pages)
            self._cache[(guild_id, channel_id)] = res
            return res

    async def set(self, guild_id: int, channel_id: int, settings: Settings) -> None:
        conf = await self._get(guild_id, channel_id)
        settings = conf.apply(settings)
        self._cache[(guild_id, channel_id)] = settings
        kwargs = settings.asdict()
        async with self.db.get_session() as s:
            row = CrosspostSettings(
                guild_id=guild_id,
                channel_id=channel_id,
                **kwargs,
            )
            query = s.insert.rows(row)
            query = query.on_conflict(
                CrosspostSettings.guild_id, CrosspostSettings.channel_id
            ).update(getattr(CrosspostSettings, key) for key in kwargs)
            await query.run()


class CrosspostContext(BContext):
    cog: Crosspost

    async def send(
        self,
        content: object = None,
        *,
        tts: bool = False,
        embed: Embed = None,
        file: File = None,
        files: list[File] = None,
        delete_after: float = None,
        nonce: int = None,
        allowed_mentions: AllowedMentions = None,
        reference: Union[Message, discord.MessageReference] = None,
        mention_author: bool = None,
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
            reference=reference,
            mention_author=mention_author,
        )
        sent_images = self.cog.sent_images
        invoking_id = self.message.id
        if entry := sent_images.get(invoking_id):
            _, messages = entry
        else:
            messages = []
            sent_images[invoking_id] = (msg.channel.id, messages)
        messages.append(msg.id)

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

    sent_images: dict[MessageID, tuple[ChannelID, list[MessageID]]]
    ongoing_tasks: dict[MessageID, asyncio.Task]
    expr_dict: dict[re.Pattern, Callable[[CrosspostContext, str], Awaitable[bool]]]

    def __init__(self, bot: BeattieBot):
        self.bot = bot
        self.config = Config(bot)
        with open("config/headers.toml") as fp:
            self.headers = toml.load(fp)
        self.session = aiohttp.ClientSession(loop=bot.loop)
        self.parser = etree.HTMLParser()
        self.expr_dict = {
            expr: getattr(self, f"display_{name.partition('_')[0].lower()}_images")
            for name, expr in globals().items()
            if name.endswith("URL_EXPR")
        }
        self.login_task = self.bot.loop.create_task(self.pixiv_login_loop())
        self.init_task = bot.loop.create_task(self.__init())
        if (ongoing_tasks := bot.extra.get("crosspost_ongoing_tasks")) is not None:
            self.ongoing_tasks = ongoing_tasks
            self.sent_images = bot.extra["crosspost_sent_images"]
        else:
            self.sent_images = {}
            self.ongoing_tasks = {}
            bot.extra["crosspost_ongoing_tasks"] = self.ongoing_tasks
            bot.extra["crosspost_sent_images"] = self.sent_images

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
        filesize_limit: Optional[int] = ...,
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
        filesize_limit: Optional[int] = ...,
    ) -> _IO:
        ...

    async def save(
        self,
        img_url: str,
        *,
        fp=None,
        seek_begin: bool = True,
        use_default_headers: bool = True,
        headers: dict[str, str] = None,
        filesize_limit: int = None,
    ):
        headers = headers or {}
        img = fp or BytesIO()
        async with self.get(
            img_url, use_default_headers=use_default_headers, headers=headers
        ) as img_resp:
            if (
                filesize_limit is not None
                and img_resp.content_length is not None
                and img_resp.content_length > filesize_limit
            ):
                raise ResponseError(413)  # yes I know that's not how this works
            async for chunk in img_resp.content.iter_any():
                img.write(chunk)
        if seek_begin:
            img.seek(0)
        return img

    async def process_links(self, ctx: CrosspostContext) -> None:
        content = remove_spoilers(ctx.message.content)
        me = ctx.me
        channel = ctx.channel
        assert isinstance(me, discord.Member)
        assert isinstance(channel, discord.TextChannel)
        do_suppress = (
            channel.permissions_for(me).manage_messages
            and await self.get_mode(ctx) == 2
        )
        for expr, func in self.expr_dict.items():
            for link in expr.findall(content):
                try:
                    if await func(ctx, link) and do_suppress:
                        await ctx.message.edit(suppress=True)
                        do_suppress = False
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
        me = guild.me
        assert isinstance(channel, discord.TextChannel)
        assert isinstance(me, discord.Member)
        if not me.permissions_in(channel).send_messages:
            return
        if not (await self.config.get(message)).auto:
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
        if record := self.sent_images.pop(message_id, None):
            channel_id, messages = record
            for message_id in messages:
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
        headers: dict[str, str] = None,
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
        return (await self.config.get(ctx.message)).mode or 1

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

    async def display_twitter_images(self, ctx: CrosspostContext, link: str) -> bool:
        if await self.get_mode(ctx) == 1:
            return False

        link = f"https://{link}"

        async with self.get(link) as resp:
            root = etree.fromstring(await resp.read(), self.parser)

        try:
            tweet = root.xpath(TWEET_SELECTOR)[0]
        except IndexError:
            await ctx.send("Failed to get tweet. Maybe the account is locked?")
            return False

        if imgs := tweet.xpath(TWITTER_IMG_SELECTOR):
            for img in imgs:
                url = img.get("src")
                await self.send(ctx, f"{url}:orig")
            return True
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

            try:
                stdout = await try_wait_for(proc)
            except asyncio.TimeoutError:
                await ctx.send("Gif took too long to process.")
                return False

            gif.write(stdout)
            gif.seek(0)

            file = File(gif, filename)

            msg = await ctx.send(file=file)
            return not msg.content.startswith("Image too large to upload")
        else:
            return False

    async def display_pixiv_images(self, ctx: CrosspostContext, link: str) -> bool:
        if "mode" in link:
            link = re.sub(r"(?<=mode=)\w+", "medium", link)
        elif "illust_id" in link:
            link = f"{link}&mode=medium"
        link = link.replace("http://", "https://")
        if match := re.search(r"(?:illust_id=|artworks/)(\d+)", link):
            illust_id = match.group(1)
        else:
            await ctx.send("Failed to find illust ID in pixiv link. This is a bug.")
            return False
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
            return False

        headers = {**self.pixiv_headers, "referer": link}
        guild = ctx.guild
        assert guild is not None
        filesize_limit = guild.filesize_limit
        content = None

        if single := res["meta_single_page"]:
            img_url = single["original_image_url"]
            if "ugoira" in img_url:
                try:
                    file = await self.get_ugoira(illust_id)
                except asyncio.TimeoutError:
                    await ctx.send("Ugoira took too long to process.")
                    return False
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
        else:
            return False
        return True

    async def save_pixiv(
        self, img_url: str, headers: dict[str, str], filesize_limit: int
    ) -> tuple[Optional[str], File]:
        content = None
        try:
            img = await self.save(
                img_url, headers=headers, filesize_limit=filesize_limit
            )
        except ResponseError as e:
            if e.code == 413:
                img_url = img_url.replace("img-original", "img-master")
                head, _, _ext = img_url.rpartition(".")
                img_url = f"{head}_master1200.jpg"
                img = await self.save(img_url, headers=headers)
                content = "Full size too large, standard resolution used."
            else:
                raise e from None
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
            stdout = await try_wait_for(proc)

        img = BytesIO(stdout)
        img.seek(0)
        name = f"{illust_id}.gif"
        return File(img, name)

    async def display_hiccears_images(self, ctx: CrosspostContext, link: str) -> bool:
        async with self.get(link, headers=self.hiccears_headers) as resp:
            root = etree.fromstring(await resp.read(), self.parser)

        if single_image := root.xpath(HICCEARS_IMG_SELECTOR):
            a = single_image[0]
            href = a.get("href").lstrip(".")
            url = f"https://{resp.host}{href}"
            await self.send(ctx, url)
            return True

        thumbs = root.xpath(HICCEARS_THUMB_SELECTOR)

        num_images = len(thumbs)

        if num_images == 0:
            await ctx.send(
                "Hiccears login expired. <@!140293604726800385> needs to fix this. >:("
            )
            return False

        max_pages = await self.get_max_pages(ctx)

        if max_pages == 0:
            max_pages = num_images

        pages_remaining = num_images - max_pages
        for thumb in thumbs[:max_pages]:
            href = thumb.get("src").lstrip(".").replace("thumbnails", "imgs")[:-4]
            url = f"https://{resp.host}{href}.jpg"
            await self.send(ctx, url)
        if pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            message = f"{pages_remaining} more image{s} at <{link}>"
            await ctx.send(message)
        return True

    async def display_tumblr_images(self, ctx: CrosspostContext, link: str) -> bool:
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
        return True

    async def display_mastodon_images(self, ctx: CrosspostContext, link: str) -> bool:
        if (match := MASTODON_URL_GROUPS.match(link)) is None:
            return False
        api_url = MASTODON_API_FMT.format(*match.groups())
        try:
            async with self.get(api_url, use_default_headers=False) as resp:
                post = await resp.json()
        except (ResponseError, aiohttp.ClientError):
            return False

        if not (images := post.get("media_attachments")):
            return False

        mode = await self.get_mode(ctx)

        idx = 0 if mode != 1 or post["sensitive"] else 1

        all_embedded = True

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

                    try:
                        stdout = await try_wait_for(proc)
                    except asyncio.TimeoutError:
                        await ctx.send("Gif took too long to process.")
                        all_embedded = False
                        continue

                img = BytesIO(stdout)

                filename = f"{url.rpartition('/')[2]}.gif"
                file = File(img, filename)
                msg = await ctx.send(file=file)
                if all_embedded and msg.content.startswith("Image too large to upload"):
                    all_embedded = False
            else:
                await self.send(ctx, url)
        return all_embedded

    async def display_inkbunny_images(self, ctx: CrosspostContext, sub_id: str) -> bool:
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
        return True

    async def display_imgur_images(self, ctx: CrosspostContext, album_id: str) -> bool:
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
        return True

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
        """Change image crosspost settings.

        Each subcommand takes, in addition to the configuration value, an optional \
target, which specifies a channel or category to apply the setting to, instead of \
applying it to the guild as a whole."""
        pass

    @crosspost.command()
    async def auto(
        self,
        ctx: BContext,
        enabled: bool,
        *,
        target: Union[CategoryChannel, TextChannel] = None,
    ) -> None:
        """Enable or disable automatic crossposting."""
        guild = ctx.guild
        assert guild is not None
        settings = Settings(auto=enabled)
        await self.config.set(guild.id, target.id if target else 0, settings)
        fmt = "en" if enabled else "dis"
        message = f"Crossposting images {fmt}abled"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command()
    async def mode(
        self,
        ctx: BContext,
        mode: str,
        *,
        target: Union[CategoryChannel, TextChannel] = None,
    ) -> None:
        """Change image crossposting mode.

        link: send a link to images when available
        upload: always upload image files

        Fetching images from Twitter is disabled in link mode.
        When in upload mode and the bot has the Manage Messages permission, it'll \
remove embeds from messages it processes successfully."""
        if mode == "link":
            crosspost_mode = 1
        elif mode == "upload":
            crosspost_mode = 2
        else:
            raise commands.BadArgument(mode)

        guild = ctx.guild
        assert guild is not None

        settings = Settings(mode=crosspost_mode)

        await self.config.set(guild.id, target.id if target else 0, settings)
        message = "Crosspost mode updated"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command()
    async def pages(
        self,
        ctx: BContext,
        max_pages: int,
        *,
        target: Union[CategoryChannel, TextChannel] = None,
    ) -> None:
        """Set the maximum number of images to send.

        Set to 0 for no limit."""
        guild = ctx.guild
        assert guild is not None
        settings = Settings(max_pages=max_pages)
        await self.config.set(guild.id, target.id if target else 0, settings)
        message = f"Max crosspost pages set to {max_pages}"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    async def crosspost_error(self, ctx: BContext, e: Exception) -> None:
        if isinstance(e, BadUnionArgument):
            inner = e.errors[0]
            assert isinstance(inner, ChannelNotFound)
            await ctx.send(
                f"Could not resolve `{inner.argument}` as a category or channel"
            )
        else:
            await ctx.bot.handle_error(ctx, e)

    auto_error = auto.error(crosspost_error)
    mode_error = mode.error(crosspost_error)
    pages_error = pages.error(crosspost_error)

    @commands.command()
    async def post(self, ctx: BContext, *, _: str) -> None:
        """Embed images in the given links regardless of the auto setting."""
        new_ctx = await self.bot.get_context(ctx.message, cls=CrosspostContext)
        await self.process_links(new_ctx)

    @commands.command(aliases=["_"])
    async def nopost(self, ctx: BContext, *, _: str = "") -> None:
        """Ignore links in the following message.

        You can also use ||spoiler tags|| to achieve the same thing."""
        pass


def setup(bot: BeattieBot) -> None:
    bot.add_cog(Crosspost(bot))
