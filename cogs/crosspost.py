from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
import urllib.parse as urlparse
from asyncio import subprocess
from base64 import b64encode
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from hashlib import md5
from html import unescape as html_unescape
from io import BytesIO
from itertools import groupby
from operator import itemgetter
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal, Mapping, Self
from zipfile import ZipFile

import aiohttp
import discord
import toml
from discord import CategoryChannel, File, Message, PartialMessageable, Thread
from discord.ext import commands
from discord.ext.commands import (
    BadArgument,
    BadUnionArgument,
    ChannelNotFound,
    Cog,
    Converter,
    FlagConverter,
)
from discord.utils import sleep_until, snowflake_time, time_snowflake, utcnow
from lxml import etree, html
from tldextract.tldextract import TLDExtract

from bot import BeattieBot
from context import BContext
from utils.aioutils import squash_unfindable
from utils.checks import is_owner_or
from utils.contextmanagers import get
from utils.etc import display_bytes, remove_spoilers, translate_markdown
from utils.exceptions import ResponseError
from utils.type_hints import GuildMessageable

GLOB_SITE_EXCLUDE = {
    "tenor.com",
    "giphy.com",
    "pixiv.net",
    "twitter.com",
    "fxtwitter.com",
    "vxtwitter.com",
    "sxtwitter.com",
    "zztwitter.com",
    "twxtter.com",
    "twittervx.com",
    "inkbunny.net",
    "imgur.com",
    "tumblr.com",
    "rule34.xxx",
    "hiccears.com",
    "gelbooru.com",
    "fanbox.cc",
    "discord.gg",
    "youtu.be",
    "youtube.com",
    "itch.io",
    "crepu.net",
    "x.com",
    "fixupx.com",
    "fixvx.com",
}

OG_IMAGE = ".//meta[@property='og:image']"
OG_TITLE = ".//meta[@property='og:title']"
OG_DESCRIPTION = ".//meta[@property='og:description']"

TWITTER_URL_EXPR = re.compile(
    r"https?://(?:(?:www|mobile|m)\.)?(?:(?:.x|zz)?tw[ix]tter|(?:fix(?:up|v))?x)(?:vx)?"
    r"\.com/[^\s/]+/status/(\d+)"
)
TWITTER_TEXT_TRIM = re.compile(r" ?https://t\.co/\w+$")
TWITTER_VIDEO_WIDTH = re.compile(r"vid/(\d+)x")

PIXIV_URL_EXPR = re.compile(
    r"https?://(?:www\.)?pixiv\.net/(?:(?:en/)?artworks/|"
    r"member_illust\.php\?(?:\w+=\w+&?)*illust_id=|i/)(\d+)"
)

HICCEARS_URL_EXPR = re.compile(
    r"https?://(?:www\.)?hiccears\.com/(?:[\w-]+/)?"
    r"(?:contents/[\w-]+|file/[\w-]+/[\w-]+/preview)"
)
HICCEARS_IMG_SELECTOR = ".//a[contains(@href, 'imgs')]"
HICCEARS_THUMB_SELECTOR = ".//a[contains(@class, 'photo-preview')]"
HICCEARS_TEXT_SELECTOR = ".//div[contains(@class, 'widget-box-content')]"
HICCEARS_TITLE_SELECTOR = ".//h2[contains(@class, 'section-title')]"
HICCEARS_NEXT_SELECTOR = ".//a[contains(@class, 'right')]"

TUMBLR_URL_EXPR = re.compile(
    r"https?://(?:(?:www\.)?tumb(?:lr|ex)\.com/)?"
    r"([\w-]+)(?:/|\.tumblr(?:\.com)?/post/)(\d+)"
)
TUMBLR_SCRIPT_SELECTOR = ".//script[contains(text(),'window.launcher')]"

MASTODON_URL_EXPR = re.compile(r"(https?://([^\s/]+)/(?:.+/)+([\w-]+))(?:>|$|\s)")
MASTODON_API_FMT = "https://{}/api/v1/statuses/{}"

INKBUNNY_URL_EXPR = re.compile(
    r"https?://(?:www\.)?inkbunny\.net/"
    r"(?:s/|submissionview\.php\?id=)(\d+)(?:-p\d+-)?(?:#.*)?"
)
INKBUNNY_API_FMT = "https://inkbunny.net/api_{}.php"

IMGUR_URL_EXPR = re.compile(r"https?://(?:www\.)?imgur\.com/(a|gallery/)?(\w+)")

BOORU_API_PARAMS = {"page": "dapi", "s": "post", "q": "index", "json": "1"}

GELBOORU_URL_EXPR = re.compile(
    r"https?://gelbooru\.com/index\.php\?(?:\w+=[^>&\s]+&?){2,}"
)
GELBOORU_API_URL = "https://gelbooru.com/index.php"

R34_URL_EXPR = re.compile(r"https?://rule34\.xxx/index\.php\?(?:\w+=[^&]+&?){2,}")
R34_API_URL = "https://rule34.xxx/index.php"

FANBOX_URL_EXPR = re.compile(r"https?://(?:[\w-]+.)?fanbox\.cc(?:/.+)*?/posts/\d+")

LOFTER_URL_EXPR = re.compile(r"https?://[\w-]+\.lofter\.com/post/\w+")
LOFTER_IMG_SELECTOR = ".//a[contains(@class, 'imgclasstag')]/img"
LOFTER_TEXT_SELECTOR = (
    ".//div[contains(@class, 'content')]/div[contains(@class, 'text')]"
)

MISSKEY_URL_EXPR = re.compile(r"https?://misskey\.\w+/notes/\w+")
MISSKEY_URL_GROUPS = re.compile(r"https?://(misskey\.\w+)/notes/(\w+)")

POIPIKU_URL_EXPR = re.compile(r"https?://poipiku\.com/\d+/\d+\.html")
POIPIKU_URL_GROUPS = re.compile(r"https?://poipiku\.com/(\d+)/(\d+)\.html")

BSKY_URL_EXPR = re.compile(r"https?://bsky\.app/profile/([^/]+)/post/(.+)")
BSKY_XRPC_FMT = (
    "https://bsky.social/xrpc/com.atproto.repo.getRecord"
    "?repo={}&collection=app.bsky.feed.post&rkey={}"
)

PAHEAL_URL_EXPR = re.compile(r"https?://rule34\.paheal\.net/post/view/(\d+)")
PAHEAL_IMG_SELECTOR = ".//img[@id='main_image']"
PAHEAL_SOURCE_SELECTOR = ".//tr[@data-row='Source Link']/td//a"

FURAFFINITY_URL_EXPR = re.compile(
    r"https?://(?:www\.)?(?:[fv]x)?f[ux]raffinity\.net/view/(\d+)"
)

YGAL_URL_EXPR = re.compile(r"https?://(?:(?:old|www)\.)?y-gallery\.net/view/(\d+)")
YGAL_FULLSIZE_EXPR = re.compile(r"""popup\((['"])(?P<link>[^\1]*?)\1""")
YGAL_IMG_SELECTOR = "//img[@id='idPreviewImage']"
YGAL_TEXT_SELECTOR = "//div[@id='artist-comment']//div[contains(@class, 'commentData')]"

YT_COMMUNITY_URL_EXPR = re.compile(
    r"https?://(?:www\.)?youtube\.com/(?:post/|channel/[^/]+/community\?lb=)([\w-]+)"
)
YT_SCRIPT_SELECTOR = ".//script[contains(text(),'responseContext')]"

E621_URL_EXPR = re.compile(r"https?://(?:www\.)?e621\.net/post(?:s|/show)/(\d+)")

PILLOWFORT_URL_EXPR = re.compile(r"https?://(?:www\.)?pillowfort\.social/posts/\d+")

HANDLER_EXPR: list[tuple[str, re.Pattern]] = [
    (name.removesuffix("_URL_EXPR").lower(), expr)
    for name, expr in globals().items()
    if name.endswith("_URL_EXPR")
]


MESSAGE_CACHE_TTL: int = 60 * 60 * 24  # one day in seconds

ConfigTarget = GuildMessageable | CategoryChannel


async def try_wait_for(
    proc: asyncio.subprocess.Process,
    *,
    timeout: float | None = 120,
    kill_timeout: float | None = 5,
) -> bytes:
    try:
        out, _err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        await gently_kill(proc, timeout=kill_timeout)
        raise
    else:
        return out


async def gently_kill(proc: asyncio.subprocess.Process, *, timeout: float | None):
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()


def too_large(message: Message) -> bool:
    return message.content.startswith("Image too large to upload")


class Site(Converter):
    async def convert(self, ctx: BContext, argument: str) -> str:
        if argument not in HANDLER_DICT:
            raise BadArgument
        return argument


class PostFlags(FlagConverter, case_insensitive=True, delimiter="="):
    pages: int | None
    text: bool | None


class Fragment:
    pass


class FileFragment(Fragment):
    cog: Crosspost
    urls: tuple[str, ...]
    headers: dict[str, str] | None
    use_default_headers: bool
    filename: str
    img: BytesIO | None
    dl_task: asyncio.Task | None
    postprocess: PP | None
    pp_extra: Any

    def __init__(
        self,
        cog: Crosspost,
        *urls: str,
        filename: str = None,
        headers: dict[str, str] = None,
        use_default_headers: bool = False,
        postprocess: PP = None,
        pp_extra: Any = None,
    ):
        self.cog = cog
        self.urls = urls
        self.postprocess = postprocess
        self.pp_extra = pp_extra
        self.headers = headers
        self.use_default_headers = use_default_headers

        if filename is None:
            filename = re.findall(r"[\w. -]+\.[\w. -]+", urls[0])[-1]
        if filename is None:
            raise RuntimeError(f"could not parse filename from URL: {urls[0]}")
        for ext, sub in [
            ("jfif", "jpeg"),
            ("pnj", "png"),
        ]:
            if filename.endswith(f".{ext}"):
                filename = f"{filename.removesuffix(ext)}{sub}"
        self.filename = filename

        self.img = None
        self.dl_task = None

    def save(self) -> Awaitable[None]:
        if self.dl_task is None:
            self.dl_task = asyncio.Task(self._save())
        return self.dl_task

    async def _save(self):
        img, filename = await self.cog.save(
            *self.urls,
            headers=self.headers,
            use_default_headers=self.use_default_headers,
        )

        if filename is not None:
            self.filename = filename

        if self.postprocess is not None:
            img = await self.postprocess(self, img, self.pp_extra)

        self.img = img


PP = Callable[[FileFragment, BytesIO, Any], Awaitable[BytesIO]]


class FallbackFragment(Fragment):
    preferred_url: str
    fallback_url: str
    headers: dict[str, str] | None
    preferred_len: int | None
    preferred_frag: FileFragment | None
    fallback_frag: FileFragment | None

    def __init__(
        self,
        cog: Crosspost,
        preferred_url: str,
        fallback_url: str,
        headers: dict[str, str] | None,
    ):
        self.cog = cog
        self.preferred_url = preferred_url
        self.fallback_url = fallback_url
        self.headers = headers

        self.preferred_frag = None
        self.fallback_frag = None
        self.preferred_len = None

    async def to_file(self, ctx: CrosspostContext) -> FileFragment:
        if self.preferred_len is None:
            async with self.cog.get(
                self.preferred_url,
                "HEAD",
                use_default_headers=False,
                headers=self.headers,
            ) as resp:
                self.preferred_len = resp.content_length

        guild = ctx.guild
        assert guild is not None
        if self.preferred_len is not None and guild.filesize_limit > self.preferred_len:

            if (frag := self.preferred_frag) is None:
                frag = self.preferred_frag = FileFragment(
                    ctx.cog,
                    self.preferred_url,
                    headers=self.headers,
                    use_default_headers=False,
                )
        else:
            if (frag := self.fallback_frag) is None:
                frag = self.fallback_frag = FileFragment(
                    ctx.cog,
                    self.fallback_url,
                    headers=self.headers,
                    use_default_headers=False,
                )

        return frag


class TextFragment(Fragment):
    def __init__(self, content: str, force: bool):
        self.content = content
        self.force = force

    def __str__(self) -> str:
        return self.content


class FragmentQueue:
    cog: Crosspost
    fragments: list[Fragment]

    def __init__(self, ctx: CrosspostContext, link: str):
        assert ctx.command is not None
        self.link = link
        self.cog = ctx.command.cog
        self.fragments = []

    def push_file(
        self,
        *urls: str,
        filename: str = None,
        postprocess: PP = None,
        pp_extra: Any = None,
        headers: dict[str, str] = None,
    ):
        self.fragments.append(
            FileFragment(
                self.cog,
                *urls,
                filename=filename,
                postprocess=postprocess,
                pp_extra=pp_extra,
                headers=headers,
            )
        )

    def push_fallback(
        self,
        preferred_url: str,
        fallback_url: str,
        headers: dict[str, str],
    ):
        self.fragments.append(
            FallbackFragment(
                self.cog,
                preferred_url,
                fallback_url,
                headers,
            )
        )

    def push_text(self, text: str, force: bool = False):
        self.fragments.append(TextFragment(text, force))

    async def resolve(self, ctx: CrosspostContext) -> bool:
        if not self.fragments:
            return False

        fragments = self.fragments[:]

        guild = ctx.guild
        assert guild is not None
        limit = guild.filesize_limit
        do_text = await self.cog.should_post_text(ctx)
        text = ""
        file_batch = []
        batch_size = 0
        max_pages = await self.cog.get_max_pages(ctx)

        to_dl = []

        for idx, frag in enumerate(fragments):
            if isinstance(frag, FallbackFragment):
                fragments[idx] = frag = await frag.to_file(ctx)
            if isinstance(frag, FileFragment):
                to_dl.append(frag)
            if max_pages and len(to_dl) >= max_pages:
                break

        for frag in to_dl:
            frag.save()

        async def senf_files():
            nonlocal batch_size
            if file_batch:
                await ctx.send(files=file_batch)
                file_batch.clear()
                batch_size = 0

        def send_text():
            nonlocal text
            send = text.strip()
            text = ""
            if send:
                return ctx.send(send, suppress_embeds=True)
            else:
                return asyncio.sleep(0)

        num_files = 0
        for frag in fragments:
            if isinstance(frag, TextFragment):
                if frag.force:
                    await senf_files()
                    await ctx.send(frag.content, suppress_embeds=True)
                else:
                    text = f"{text}\n{frag}"
            else:
                num_files += 1
                if max_pages and num_files > max_pages:
                    continue
                assert isinstance(frag, FileFragment)
                if do_text and text and not (max_pages and num_files > max_pages):
                    await send_text()
                await frag.save()
                img = frag.img
                if img is None:
                    raise RuntimeError("frag.save failed to set img")
                size = len(img.getbuffer())
                if size > limit:
                    await senf_files()
                    await ctx.send(frag.urls[0])
                    continue
                if batch_size + size > limit or len(file_batch) == 10:
                    await senf_files()
                batch_size += size
                img.seek(0)
                file_batch.append(File(img, frag.filename))

        if file_batch:
            await senf_files()

        if do_text and text:
            await send_text()

        pages_remaining = max_pages and num_files - max_pages

        if pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            message = f"{pages_remaining} more item{s} at {self.link}"
            await ctx.send(message, suppress_embeds=True)

        return True


async def gif_pp(frag: FileFragment, img: BytesIO, _) -> BytesIO:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-i",
        frag.urls[0],
        "-i",
        frag.urls[0],
        "-filter_complex",
        "[0:v]palettegen[p];[1:v][p]paletteuse",
        "-f",
        "gif",
        "pipe:1",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        stdout = await try_wait_for(proc)
    except asyncio.TimeoutError:
        return img
    else:
        return BytesIO(stdout)


async def ugoira_pp(frag: FileFragment, img: BytesIO, illust_id: str) -> BytesIO:
    url = "https://app-api.pixiv.net/v1/ugoira/metadata"
    params = {"illust_id": illust_id}
    headers = frag.headers
    async with frag.cog.get(
        url, params=params, use_default_headers=False, headers=headers
    ) as resp:
        res = (await resp.json())["ugoira_metadata"]

    zip_url = res["zip_urls"]["medium"]
    zip_url = re.sub(r"ugoira\d+x\d+", "ugoira1920x1080", zip_url)

    headers = frag.headers or {}

    headers = {
        **headers,
        "referer": f"https://www.pixiv.net/en/artworks/{illust_id}",
    }

    zip_bytes, _ = await frag.cog.save(
        zip_url, headers=headers, use_default_headers=False
    )
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
        stdout = await try_wait_for(proc, timeout=120)

    frag.filename = f"{illust_id}.gif"
    img = BytesIO(stdout)
    img.seek(0)
    return img


class Settings:
    __slots__ = ("auto", "max_pages", "cleanup", "text")

    auto: bool | None
    max_pages: int | None
    cleanup: bool | None
    text: bool | None

    def __init__(
        self,
        auto: bool = None,
        max_pages: int = None,
        cleanup: bool = None,
        text: bool = None,
    ):
        self.auto = auto
        self.max_pages = max_pages
        self.cleanup = cleanup
        self.text = text

    def __str__(self):
        return ", ".join(
            f"{k}={v}" for k in self.__slots__ if (v := getattr(self, k)) is not None
        )

    def apply(self, other: Settings) -> Settings:
        """Returns a Settings with own values overwritten by non-None values of other"""
        out = copy.copy(self)
        for attr in self.__slots__:
            if (value := getattr(other, attr)) is not None:
                setattr(out, attr, value)

        return out

    def asdict(self) -> dict[str, Any]:
        return {k: v for k in self.__slots__ if (v := getattr(self, k)) is not None}

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> Self:
        return cls(*(row[attr] for attr in cls.__slots__))


class Database:
    def __init__(self, bot: BeattieBot, cog: Crosspost):
        self.pool = bot.pool
        self.bot = bot
        self.cog = cog
        self._settings_cache: dict[tuple[int, int], Settings] = {}
        self._blacklist_cache: dict[int, set[str]] = {}
        self._expiry_deque: deque[int] = deque()
        self._message_cache: dict[int, list[int]] = {}
        self.overrides: dict[int, Settings] = {}

    async def async_init(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public.crosspost (
                    guild_id bigint NOT NULL,
                    channel_id bigint NOT NULL,
                    auto boolean,
                    max_pages integer,
                    cleanup boolean,
                    text boolean,
                    PRIMARY KEY(guild_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS public.crosspostmessage (
                    sent_message bigint NOT NULL PRIMARY KEY,
                    invoking_message bigint NOT NULL
                );

                CREATE TABLE IF NOT EXISTS public.crosspostblacklist (
                    guild_id bigint NOT NULL,
                    site text NOT NULL,
                    PRIMARY KEY(guild_id, site)
                );
                """
            )

            rows = await conn.fetch(
                """
                SELECT *
                FROM crosspostmessage
                WHERE invoking_message > $1
                ORDER BY invoking_message
                """,
                time_snowflake(utcnow() - timedelta(seconds=MESSAGE_CACHE_TTL)),
            )

            for invoking_message, elems in groupby(
                rows,
                key=itemgetter("invoking_message"),
            ):
                self._expiry_deque.append(invoking_message)
                self._message_cache[invoking_message] = [
                    elem["sent_message"] for elem in elems
                ]
            self._expiry_task = asyncio.create_task(self._expire())

    async def _expire(self):
        try:
            while self._expiry_deque:
                entry = self._expiry_deque.popleft()
                until = snowflake_time(entry) + timedelta(seconds=MESSAGE_CACHE_TTL)
                await sleep_until(until)
                self._message_cache.pop(entry, None)
        except Exception:
            self.cog.logger.exception("Exception in message cache expiry task")

    async def get_effective_settings(self, message: Message) -> Settings:
        guild = message.guild
        assert guild is not None
        channel = message.channel

        guild_id = guild.id
        out = await self._get_settings(guild_id, 0)

        if category := getattr(channel, "category", None):
            out = out.apply(await self._get_settings(guild_id, category.id))
        if isinstance(channel, Thread):
            out = out.apply(await self._get_settings(guild_id, channel.parent_id))
        out = out.apply(await self._get_settings(guild_id, channel.id))

        if override := self.overrides.get(message.id):
            out = out.apply(override)

        return out

    async def _get_settings(self, guild_id: int, channel_id: int) -> Settings:
        try:
            return self._settings_cache[(guild_id, channel_id)]
        except KeyError:
            async with self.pool.acquire() as conn:
                config = await conn.fetchrow(
                    "SELECT * FROM crosspost WHERE guild_id = $1 AND channel_id = $2",
                    guild_id,
                    channel_id,
                )
            if config is None:
                res = Settings()
            else:
                res = Settings.from_record(config)
            self._settings_cache[(guild_id, channel_id)] = res
            return res

    async def set_settings(self, guild_id: int, channel_id: int, settings: Settings):
        if cached := self._settings_cache.get((guild_id, channel_id)):
            settings = cached.apply(settings)
        self._settings_cache[(guild_id, channel_id)] = settings
        kwargs = settings.asdict()
        cols = ",".join(kwargs)
        params = ",".join(f"${i}" for i, _ in enumerate(kwargs, 1))
        update = ",".join(f"{col}=EXCLUDED.{col}" for col in kwargs)
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO crosspost(guild_id,channel_id,{cols})
                VALUES({guild_id},{channel_id},{params})
                ON CONFLICT (guild_id,channel_id)
                DO UPDATE SET {update}
                """,
                *kwargs.values(),
            )

    async def clear_settings(self, guild_id: int, channel_id: int):
        self._settings_cache.pop((guild_id, channel_id), None)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM crosspost WHERE guild_id = $1 AND channel_id = $2",
                guild_id,
                channel_id,
            )

    async def clear_settings_all(self, guild_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "DELETE FROM crosspost WHERE guild_id = $1 RETURNING channel_id",
                guild_id,
            )

        for row in rows:
            self._settings_cache.pop((guild_id, row["channel_id"]), None)

    async def get_sent_messages(self, invoking_message: int) -> list[int]:
        if sent_messages := self._message_cache.get(invoking_message):
            return sent_messages
        elif (
            utcnow() - snowflake_time(invoking_message)
        ).total_seconds() > MESSAGE_CACHE_TTL - 3600:  # an hour's leeway
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM crosspostmessage WHERE invoking_message = $1",
                    invoking_message,
                )
                return [row["sent_message"] for row in rows]
        else:
            return []

    async def add_sent_message(self, invoking_message: int, sent_message: int):
        if (messages := self._message_cache.get(invoking_message)) is None:
            messages = []
            self._message_cache[invoking_message] = messages
            self._expiry_deque.append(invoking_message)
        messages.append(sent_message)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO crosspostmessage(sent_message, invoking_message)
                VALUES ($1, $2)
                """,
                sent_message,
                invoking_message,
            )
        if self._expiry_task.done():
            self._expiry_task = asyncio.create_task(self._expire())

    async def del_sent_messages(self, invoking_message: int):
        self._message_cache.pop(invoking_message, None)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM crosspostmessage WHERE invoking_message = $1",
                invoking_message,
            )

    async def get_blacklist(self, guild_id: int) -> set[str]:
        try:
            return self._blacklist_cache[guild_id]
        except KeyError:
            res = set()
            async with self.pool.acquire() as conn:
                for row in await conn.fetch(
                    "SELECT * FROM crosspostblacklist WHERE guild_id = $1",
                    guild_id,
                ):
                    res.add(row["site"])

            self._blacklist_cache[guild_id] = res
            return res

    async def add_blacklist(self, guild_id: int, site: str) -> bool:
        blacklist = await self.get_blacklist(guild_id)
        if site in blacklist:
            return False

        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO crosspostblacklist VALUES ($1, $2)",
                guild_id,
                site,
            )

        blacklist.add(site)

        return True

    async def del_blacklist(self, guild_id: int, site: str) -> bool:
        blacklist = await self.get_blacklist(guild_id)
        try:
            blacklist.remove(site)
        except KeyError:
            return False

        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM crosspostblacklist WHERE guild_id = $1 AND site = $2",
                guild_id,
                site,
            )

        return True


class CrosspostContext(BContext):
    cog: Crosspost

    async def send(self, content: str = None, **kwargs: Any) -> Message:
        task = asyncio.create_task(
            self._send(
                content,
                **kwargs,
            )
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError as e:
            await asyncio.wait_for(task, timeout=None)
            raise e from None

    async def _send(
        self,
        content: str = None,
        *,
        file: File = None,
        **kwargs: Any,
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
            file=file,
            **kwargs,
        )

        await self.cog.db.add_sent_message(self.message.id, msg.id)

        return msg


class Crosspost(Cog):
    """Crossposts images from tweets and other social media"""

    bot: BeattieBot

    hiccears_headers: dict[str, str] = {}
    imgur_headers: dict[str, str] = {}
    pixiv_headers: dict[str, str] = {
        "App-OS": "android",
        "App-OS-Version": "4.4.2",
        "App-Version": "5.0.145",
        "User-Agent": "PixivAndroidApp/5.0.234 (Android 11; Pixel 5)",
    }
    fanbox_headers: dict[str, str] = {
        "Accept": "application/json, text/plain, */*",
        "Origin": "https://www.fanbox.cc",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    }
    ygal_headers: dict[str, str] = {}
    inkbunny_sid: str = ""
    mastodon_auth: dict[str, dict[str, str]]
    e621_key: str
    e621_user: str
    twitter_method: Literal["fxtwitter"] | Literal["vxtwitter"] = "fxtwitter"

    ongoing_tasks: dict[int, asyncio.Task]

    def __init__(self, bot: BeattieBot):
        self.bot = bot
        self.db = Database(bot, self)
        try:
            with open("config/headers.toml") as fp:
                self.headers = toml.load(fp)
        except FileNotFoundError:
            self.headers = {}
        self.parser = html.HTMLParser(encoding="utf-8")
        self.xml_parser = etree.XMLParser(encoding="utf-8")
        if (ongoing_tasks := bot.extra.get("crosspost_ongoing_tasks")) is not None:
            self.ongoing_tasks = ongoing_tasks
        else:
            self.ongoing_tasks = {}
            bot.extra["crosspost_ongoing_tasks"] = self.ongoing_tasks
        self.tldextract = TLDExtract(suffix_list_urls=())
        self.logger = logging.getLogger("beattie.crosspost")

    async def cog_load(self):
        self.session = aiohttp.ClientSession()
        self.login_task = asyncio.create_task(self.pixiv_login_loop())
        with open("config/logins.toml") as fp:
            data = toml.load(fp)

        self.gelbooru_params = data["gelbooru"]

        imgur_id = data["imgur"]["id"]
        self.imgur_headers["Authorization"] = f"Client-ID {imgur_id}"

        self.hiccears_headers = data["hiccears"]

        ib_login = data["inkbunny"]

        url = INKBUNNY_API_FMT.format("login")
        async with self.get(url, method="POST", params=ib_login) as resp:
            json = await resp.json()
            self.inkbunny_sid = json["sid"]

        self.mastodon_auth = data.get("mastodon", {})

        self.ygal_headers = data["ygal"]

        if e621 := data.get("e621"):
            self.e621_key = e621["api_key"]
            self.e621_user = e621["user"]
        else:
            self.e621_key = ""
            self.e621_user = ""

        await self.db.async_init()

    def cog_check(self, ctx: BContext) -> bool:
        return ctx.guild is not None

    async def pixiv_login_loop(self):
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

            data["grant_type"] = "refresh_token"
            data["refresh_token"] = login["refresh_token"]

            hash_secret = (
                "28c1fdd170a5204386cb1313c7077b34f83e4aaf4aa829ce78c231e05b0bae2c"
            )

            now = datetime.now().isoformat()
            headers = {
                "X-Client-Time": now,
                "X-Client-Hash": md5((now + hash_secret).encode("utf-8")).hexdigest(),
            }

            while True:
                wait = 1
                try:
                    async with self.get(
                        url,
                        method="POST",
                        data=data,
                        use_default_headers=False,
                        headers=headers,
                    ) as resp:
                        res = (await resp.json())["response"]
                except Exception:
                    message = "An error occurred in the pixiv login loop"
                    self.bot.logger.exception(message)
                    await asyncio.sleep(wait)
                    wait *= 2
                else:
                    break

            self.pixiv_headers["Authorization"] = f'Bearer {res["access_token"]}'
            login["refresh_token"] = res["refresh_token"]
            with open("config/logins.toml", "w") as fp:
                toml.dump(logins, fp)
            await asyncio.sleep(res["expires_in"])

    async def cog_unload(self):
        await self.session.close()
        self.login_task.cancel()

    def get(
        self,
        *urls: str,
        method: str = "GET",
        use_default_headers: bool = True,
        session: aiohttp.ClientSession = None,
        **kwargs: Any,
    ) -> get:
        if use_default_headers:
            kwargs["headers"] = {**self.headers, **kwargs.get("headers", {})}
        return get(session or self.session, *urls, method=method, **kwargs)

    async def save(
        self,
        *img_urls: str,
        use_default_headers: bool = True,
        headers: dict[str, str] = None,
    ) -> tuple[BytesIO, str | None]:
        headers = headers or {}
        img = BytesIO()
        filename = None
        async with self.get(
            *img_urls, use_default_headers=use_default_headers, headers=headers
        ) as resp:
            if disposition := resp.content_disposition:
                filename = disposition.filename
            async for chunk in resp.content.iter_any():
                img.write(chunk)

        img.seek(0)
        return img, filename

    async def process_links(self, ctx: CrosspostContext, *, force: bool = False):
        content = remove_spoilers(ctx.message.content)
        guild = ctx.guild
        assert guild is not None
        do_suppress = await self.should_cleanup(ctx.message, guild.me)
        if force:
            blacklist = set()
        else:
            blacklist = await self.db.get_blacklist(guild.id)
        for site, (expr, func) in HANDLER_DICT.items():
            if site in blacklist:
                continue
            for args in expr.findall(content):
                try:
                    if isinstance(args, str):
                        args = [args]
                    args = map(str.strip, args)
                    if await func(self, ctx, *args) and do_suppress:
                        await squash_unfindable(ctx.message.edit(suppress=True))
                        do_suppress = False
                except ResponseError as e:
                    if e.code == 404:
                        await ctx.send("Post not found.")
                    else:
                        await ctx.bot.handle_error(ctx, e)
                except Exception as e:
                    await ctx.bot.handle_error(ctx, e)

    @Cog.listener()
    async def on_message(self, message: Message):
        if (guild := message.guild) is None or message.author.bot:
            return
        channel = message.channel
        me = guild.me

        if isinstance(channel, PartialMessageable):
            channel = await self.bot.fetch_channel(channel.id)
            assert not isinstance(channel, discord.abc.PrivateChannel)

        if not channel.permissions_for(me).send_messages:
            return
        if not (await self.db.get_effective_settings(message)).auto:
            return
        if "http" not in message.content:
            return

        ctx = await self.bot.get_context(message, cls=CrosspostContext)
        if ctx.prefix is None:
            ctx.command = self.post
            await self._post(ctx)

    @Cog.listener()
    async def on_message_edit(self, _: Message, message: Message):
        if not (sent_messages := self.db._message_cache.get(message.id)):
            return

        for message_id in sent_messages:
            try:
                msg = await message.channel.fetch_message(message_id)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                return
            else:
                if msg.embeds:
                    break
        else:
            return

        assert message.guild is not None
        if not (
            message.embeds and await self.should_cleanup(message, message.guild.me)
        ):
            return

        await message.edit(suppress=True)

    @Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        async def delete_messages(messages: list[int]):
            channel_id = payload.channel_id
            for message_id in messages:
                try:
                    await self.bot.http.delete_message(channel_id, message_id)
                except discord.NotFound:
                    pass
                except discord.Forbidden:
                    return

        message_id = payload.message_id
        messages_deleted = False
        if task := self.ongoing_tasks.get(message_id):
            task.cancel()
        if messages := await self.db.get_sent_messages(message_id):
            await delete_messages(messages)
            messages_deleted = True
        if task:
            await asyncio.wait([task])
            if messages:
                await delete_messages(messages)
                messages_deleted = True
        if messages_deleted:
            await self.db.del_sent_messages(message_id)

    async def send(
        self,
        ctx: CrosspostContext,
        link: str,
        *,
        filename: str = None,
        headers: dict[str, str] = None,
        use_default_headers: bool = True,
    ) -> Message:
        img, disp_filename = await self.save(
            link, headers=headers, use_default_headers=use_default_headers
        )
        if filename is None:
            filename = disp_filename
        if filename is None:
            filename = re.findall(r"[\w. -]+\.[\w. -]+", link)[-1]
        if filename is None:
            raise RuntimeError(f"could not parse filename from URL: {link}")
        for ext, sub in [
            ("jfif", "jpeg"),
            ("pnj", "png"),
        ]:
            if filename.endswith(f".{ext}"):
                filename = f"{filename.removesuffix(ext)}{sub}"
        file = File(img, filename)
        return await ctx.send(file=file)

    async def get_max_pages(self, ctx: BContext) -> int:
        settings = await self.db.get_effective_settings(ctx.message)
        max_pages = settings.max_pages
        if max_pages is None:
            max_pages = 4
        return max_pages

    async def should_cleanup(self, message: Message, me: discord.Member) -> bool:
        if not message.channel.permissions_for(me).manage_messages:
            return False

        settings = await self.db.get_effective_settings(message)

        return bool(settings.cleanup)

    async def should_post_text(self, ctx: BContext) -> bool:
        settings = await self.db.get_effective_settings(ctx.message)
        return bool(settings.text)

    async def display_twitter_images(
        self, ctx: CrosspostContext, tweet_id: str
    ) -> bool:
        guild = ctx.guild
        assert guild is not None
        self.logger.info(
            f"twitter ({self.twitter_method}): "
            f"{guild.id}/{ctx.channel.id}/{ctx.message.id}: {tweet_id}"
        )

        headers = {"referer": f"https://x.com/i/status/{tweet_id}"}
        api_link = f"https://api.{self.twitter_method}.com/status/{tweet_id}"

        async with self.get(
            api_link,
            use_default_headers=False,
            error_for_status=False,
        ) as resp:
            status = resp.status
            try:
                tweet = await resp.json()
                if self.twitter_method == "fxtwitter":
                    tweet = tweet["tweet"]
            except (json.JSONDecodeError, KeyError):
                await ctx.send(f"Invalid response from API (code {status})")
                return False

        match status:
            case 200:
                pass
            case 404:
                await ctx.send(
                    "Failed to fetch tweet. It may have been deleted, "
                    "or be from a private or suspended account."
                )
                return False
            case 500:
                if self.twitter_method == "vxtwitter":
                    await ctx.send(tweet.get("error", "Unspecified error."))
                    return False
                raise ResponseError(500, api_link)
            case other:
                raise ResponseError(other, api_link)

        match self.twitter_method:
            case "fxtwitter":
                media = tweet.get("media", {}).get("all")
            case "vxtwitter":
                media = tweet.get("media_extended")

        if not media:
            return False

        post_link = f"https://twitter.com/i/status/{tweet_id}"
        queue = FragmentQueue(ctx, post_link)

        url: str
        for medium in media:
            url = medium["url"]
            match medium["type"]:
                case "photo" | "image":
                    try:
                        async with self.get(
                            f"{url}:orig",
                            method="HEAD",
                            headers=headers,
                            use_default_headers=False,
                        ) as resp:
                            url = str(resp.url)
                    except ResponseError as e:
                        if e.code != 404:
                            raise e
                    queue.push_file(url)
                case "gif":
                    base = url.rpartition("/")[-1].rpartition(".")[0]
                    filename = f"{base}.gif"
                    queue.push_file(url, filename=filename, postprocess=gif_pp)
                case "video":
                    queue.push_file(url)

        if text := TWITTER_TEXT_TRIM.sub("", tweet["text"]):
            text = html_unescape(text)
            queue.push_text(f">>> {text}")

        return await queue.resolve(ctx)

    async def display_pixiv_images(self, ctx: CrosspostContext, illust_id: str) -> bool:
        guild = ctx.guild
        assert guild is not None
        self.logger.info(
            f"pixiv: {guild.id}/{ctx.channel.id}/{ctx.message.id}: {illust_id}"
        )

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

        headers = {
            **self.pixiv_headers,
            "referer": f"https://www.pixiv.net/en/artworks/{illust_id}",
        }

        post_link = f"https://www.pixiv.net/en/artworks/{illust_id}"
        queue = FragmentQueue(ctx, post_link)

        if single := res["meta_single_page"]:
            url = single["original_image_url"]

            if "ugoira" in url:
                queue.push_file(
                    url, postprocess=ugoira_pp, headers=headers, pp_extra=illust_id
                )
            else:
                queue.push_fallback(url, res["image_urls"]["large"], headers=headers)

        elif multi := res["meta_pages"]:
            for page in multi:
                queue.push_fallback(
                    page["image_urls"]["original"],
                    page["image_urls"]["large"],
                    headers=headers,
                )

        queue.push_text(f"**{res['title']}**")

        return await queue.resolve(ctx)

    async def display_hiccears_images(self, ctx: CrosspostContext, link: str) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"hiccears: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        async with self.get(link, headers=self.hiccears_headers) as resp:
            self.update_hiccears_cookies(resp)
            root = html.document_fromstring(await resp.read(), self.parser)

        queue = FragmentQueue(ctx, link)

        if link.endswith("preview"):
            queue.push_file(
                re.sub(
                    r"preview(/\d+)?",
                    "download",
                    link,
                ),
                headers=self.hiccears_headers,
            )
        else:
            while True:
                thumbs = root.xpath(HICCEARS_THUMB_SELECTOR)

                for thumb in thumbs:
                    href = f"https://{resp.host}{thumb.get('href')}"
                    queue.push_file(
                        re.sub(
                            r"preview(/\d+)?",
                            "download",
                            href,
                        ),
                        headers=self.hiccears_headers,
                    )

                if next_page := root.xpath(HICCEARS_NEXT_SELECTOR):
                    next_url = f"https://{resp.host}{next_page[0].get('href')}"
                    async with self.get(
                        next_url, headers=self.hiccears_headers
                    ) as resp:
                        self.update_hiccears_cookies(resp)
                        root = html.document_fromstring(await resp.read(), self.parser)
                else:
                    break

        if title := root.xpath(HICCEARS_TITLE_SELECTOR):
            queue.push_text(f"**{title[0].text}**")
        if elem := root.xpath(HICCEARS_TEXT_SELECTOR):
            description = elem[0].text_content().strip()
            description = description.removeprefix("Description")
            description = re.sub(r"\r?\n\t+", "", description)
            if description:
                queue.push_text(f">>> {description}")

        return await queue.resolve(ctx)

    def update_hiccears_cookies(self, resp: aiohttp.ClientResponse):
        if sess := resp.cookies.get("hiccears"):
            self.bot.logger.info("Refreshing hiccears cookies from response")

            cookie = re.sub(
                r"hiccears=\w+;REMEMBERME=(.*)",
                rf"hiccears={sess.value};REMEMBERME=\g<1>",
                self.hiccears_headers["Cookie"],
            )

            with open("config/logins.toml") as fp:
                logins = toml.load(fp)

            logins["hiccears"]["Cookie"] = cookie
            self.hiccears_headers["Cookie"] = cookie

            with open("config/logins.toml", "w") as fp:
                toml.dump(logins, fp)

    async def display_tumblr_images(
        self, ctx: CrosspostContext, blog: str, post: str
    ) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"tumblr: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {blog}/{post}"
        )

        link = f"https://tumbex.com/{blog}.tumblr/post/{post}"

        async with self.get(link) as resp:
            content = await resp.read()

        root = html.document_fromstring(content, self.parser)

        if not (script := root.xpath(TUMBLR_SCRIPT_SELECTOR)):
            return False

        data = json.loads(f"{{{script[0].text.partition('{')[-1].rpartition('}')[0]}}}")

        if (post_content := data["params"]["content"]) is None:
            await ctx.send("Post inaccessible. It may require authentication.")
            return False

        blocks: list[dict[str, str]]
        blocks = post_content["posts"][0]["blocks"][0]["content"]

        if not any(block["type"] in ("image", "video") for block in blocks):
            return False

        post_link = f"https://{blog}.tumblr.com/post/{post}"
        queue = FragmentQueue(ctx, post_link)

        for block in blocks:
            match block["type"]:
                case "text":
                    queue.push_text(f">>> {block['text']}")
                case "image":
                    url = block["hd"]
                    if url.endswith(".gifv"):
                        async with self.get(
                            url, headers={"Range": "bytes=0-2"}
                        ) as resp:
                            start = await resp.read()
                        if start.startswith(b"GIF"):
                            url = url[:-1]
                    queue.push_file(url)
                case "video":
                    queue.push_file(block["url"])

        return await queue.resolve(ctx)

    async def display_mastodon_images(
        self, ctx: CrosspostContext, link: str, site: str, post_id: str
    ) -> bool:
        info = self.tldextract(link)
        if f"{info.domain}.{info.suffix}" in GLOB_SITE_EXCLUDE:
            return False

        if auth := self.mastodon_auth.get(site):
            headers = {"Authorization": f"Bearer {auth['token']}"}
        else:
            headers = {}

        api_url = MASTODON_API_FMT.format(site, post_id)
        try:
            async with self.get(
                api_url, headers=headers, use_default_headers=False
            ) as resp:
                post = await resp.json()
        except (ResponseError, aiohttp.ClientError):
            return False

        assert ctx.guild is not None
        self.logger.info(
            f"mastodon: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        if not (images := post.get("media_attachments")):
            return False

        real_url = post["url"]
        queue = FragmentQueue(ctx, real_url)
        if real_url.casefold() != link.casefold():
            queue.push_text(real_url)

        for image in images:
            urls = [url for url in [image["remote_url"], image["url"]] if url]

            for idx, url in enumerate(urls):
                if not urlparse.urlparse(url).netloc:
                    netloc = urlparse.urlparse(str(resp.url)).netloc
                    urls[idx] = f"https://{netloc}/{url.lstrip('/')}"
            if image.get("type") == "gifv":
                filename = (
                    f"{str(resp.url).rpartition('/')[2].removesuffix('.mp4')}.gif"
                )
                queue.push_file(*urls, filename=filename, postprocess=gif_pp)
            else:
                queue.push_file(*urls)

        if content := post["content"]:
            if cw := post.get("spoiler_text"):
                queue.push_text(cw)

            fragments = html.fragments_fromstring(content, parser=self.parser)
            text = "\n".join(
                f if isinstance(f, str) else f.text_content() for f in fragments
            )
            queue.push_text(f">>> {text}")

        return await queue.resolve(ctx)

    async def display_inkbunny_images(self, ctx: CrosspostContext, sub_id: str) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"inkbunny: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {sub_id}"
        )

        url = INKBUNNY_API_FMT.format("submissions")
        params = {"sid": self.inkbunny_sid, "submission_ids": sub_id}
        post_text = await self.should_post_text(ctx)
        if post_text:
            params["show_description"] = "yes"
        async with self.get(
            url, method="POST", use_default_headers=False, params=params
        ) as resp:
            response = await resp.json()

        sub = response["submissions"][0]

        post_link = f"https://inkbunny.net/s/{sub_id}"
        queue = FragmentQueue(ctx, post_link)

        for file in sub["files"]:
            url = file["file_url_full"]
            queue.push_file(url)

        title = sub["title"]
        description = sub["description"].strip()
        queue.push_text(f"**{title}**")
        if description:
            queue.push_text(f">>> {description}")

        return await queue.resolve(ctx)

    async def display_imgur_images(
        self, ctx: CrosspostContext, fragment: str | None, album_id: str
    ) -> bool:
        assert ctx.guild is not None
        is_album = bool(fragment)
        self.logger.info(
            f"imgur: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: "
            f"{album_id} album={is_album}"
        )

        target = "album" if is_album else "image"

        async with self.get(
            f"https://api.imgur.com/3/{target}/{album_id}",
            use_default_headers=False,
            headers=self.imgur_headers,
        ) as resp:
            data = (await resp.json())["data"]

        if is_album:
            images = data["images"]
        else:
            images = [data]

        post_link = f"https://imgur.com/a/{album_id}"
        queue = FragmentQueue(ctx, post_link)

        for image in images:
            queue.push_file(image["link"])

        return await queue.resolve(ctx)

    async def display_gelbooru_images(self, ctx: CrosspostContext, link: str) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"gelbooru: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        params = {**BOORU_API_PARAMS, **self.gelbooru_params}
        post = await self.booru_helper(link, GELBOORU_API_URL, params)
        if post is None:
            return False

        queue = FragmentQueue(ctx, link)

        queue.push_file(post["file_url"])

        params["s"] = "note"
        del params["json"]
        params["post_id"] = params.pop("id")
        async with self.get(GELBOORU_API_URL, params=params) as resp:
            root = etree.fromstring(await resp.read(), self.xml_parser)

        notes = list(root)
        if notes:
            notes.sort(key=lambda n: int(n.get("y")))
            text = "\n\n".join(n.get("body") for n in notes)
            text = translate_markdown(text)
            queue.push_text(f">>> {text}")

        if source := post.get("source"):
            queue.push_text(html_unescape(source), force=True)

        return await queue.resolve(ctx)

    async def display_r34_images(self, ctx: CrosspostContext, link: str) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"r34: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        params = {**BOORU_API_PARAMS}
        post = await self.booru_helper(link, R34_API_URL, params)
        if post is None:
            return False
        queue = FragmentQueue(ctx, link)
        queue.push_file(post["file_url"])
        if source := post.get("source"):
            queue.push_text(html_unescape(source), force=True)
        return await queue.resolve(ctx)

    async def booru_helper(
        self, link: str, api_url: str, params: dict[str, str]
    ) -> dict[str, Any] | None:
        parsed = urlparse.urlparse(link)
        query = urlparse.parse_qs(parsed.query)
        page = query.get("page")
        if page != ["post"]:
            return None
        id_ = query.get("id")
        if not id_:
            return None
        id_ = id_[0]
        params["id"] = id_
        async with self.get(api_url, params=params) as resp:
            data = await resp.json()
        if not data:
            return None
        if isinstance(data, dict):
            data = data["post"]
        post = data[0]
        return post

    async def display_fanbox_images(self, ctx: CrosspostContext, link: str) -> bool:
        *_, post_id = link.rpartition("/")
        url = f"https://api.fanbox.cc/post.info?postId={post_id}"
        headers = {**self.fanbox_headers, "Referer": link}
        async with (
            aiohttp.ClientSession() as sess,
            self.get(url, headers=headers, session=sess) as resp,
        ):
            data = await resp.json()

        post = data["body"]
        body = post["body"]
        if body is None:
            return False

        guild = ctx.guild
        assert guild is not None
        self.logger.info(
            f"fanbox: {guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        queue = FragmentQueue(ctx, link)

        match post["type"]:
            case "image":
                for image in body["images"]:
                    queue.push_fallback(
                        image["originalUrl"], image["thumbnailUrl"], headers
                    )
                if text := body.get("text", "").strip():
                    queue.push_text(f">>> {text}")
            case "file":
                for file_info in body["files"]:
                    url = file_info["url"]
                    filename = file_info["name"] + "." + file_info["extension"]
                    queue.push_file(url, filename=filename)
                if text := body.get("text", "").strip():
                    queue.push_text(f">>> {text}")
            case "article":
                blocks = body["blocks"]
                image_map = body["imageMap"]
                file_map = body["fileMap"]

                if not (image_map or file_map):
                    return False

                for block in blocks:
                    match block["type"]:
                        case "p":
                            if text := block.get("text", "").strip():
                                queue.push_text(f"> {text}")
                        case "image":
                            image = image_map[block["imageId"]]
                            queue.push_fallback(
                                image["originalUrl"],
                                image["thumbnailUrl"],
                                headers,
                            )
                        case "file":
                            queue.push_file(file_map[block["fileId"]]["url"])
            case other:
                await ctx.send(f"Unrecognized post type {other}! This is a bug.")
                return False

        return await queue.resolve(ctx)

    async def display_lofter_images(self, ctx: CrosspostContext, link: str) -> bool:
        async with self.get(link, use_default_headers=False) as resp:
            root = html.document_fromstring(await resp.read(), self.parser)

        if elems := root.xpath(LOFTER_IMG_SELECTOR):
            img = elems[0]
        else:
            return False

        assert ctx.guild is not None
        self.logger.info(
            f"lofter: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        queue = FragmentQueue(ctx, link)

        queue.push_file(img.get("src"))

        if elems := root.xpath(LOFTER_TEXT_SELECTOR):
            text = elems[0].text_content()
            queue.push_text(f">>> {text}")

        return await queue.resolve(ctx)

    async def display_misskey_images(self, ctx: CrosspostContext, link: str) -> bool:
        if (match := MISSKEY_URL_GROUPS.match(link)) is None:
            return False

        assert ctx.guild is not None
        self.logger.info(
            f"misskey: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        site, post = match.groups()

        url = f"https://{site}/api/notes/show"
        body = json.dumps({"noteId": post}).encode("utf-8")

        async with self.get(
            url,
            method="POST",
            data=body,
            use_default_headers=False,
            headers={"Content-Type": "application/json"},
        ) as resp:
            data = await resp.json()

        if not (files := data["files"]):
            return False

        queue = FragmentQueue(ctx, link)

        for file in files:
            url = file["url"]
            filename = None
            pp = None
            base, _, ext = url.rpartition("/")[-1].rpartition("?")[0].rpartition(".")
            if ext == "apng":
                filename = f"{base}.gif"
                pp = gif_pp

            queue.push_file(url, filename=filename, postprocess=pp)

        if text := data["text"]:
            queue.push_text(f">>> {text}")

        return await queue.resolve(ctx)

    async def display_poipiku_images(self, ctx: CrosspostContext, link: str) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"poipiku: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        async with self.get(link, use_default_headers=False) as resp:
            root = html.document_fromstring(await resp.read(), self.parser)

        link = str(resp.url)
        if (match := POIPIKU_URL_GROUPS.match(link)) is None:
            return False

        refer = {"Referer": link}

        img = root.xpath(".//img[contains(@class, 'IllustItemThumbImg')]")[0]
        src: str = img.get("src")

        queue = FragmentQueue(ctx, link)

        if "/img/" not in src:
            src = src.removesuffix("_640.jpg").replace("//img.", "//img-org.")
            src = f"https:{src}"
            queue.push_file(src, headers=refer)

        user, post = match.groups()

        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Origin": "https://poipiku.com",
            **refer,
        }

        body = {
            "UID": user,
            "IID": post,
            "PAS": "",
            "MD": "0",
            "TWF": "-1",
        }

        async with self.get(
            "https://poipiku.com/f/ShowAppendFileF.jsp",
            method="POST",
            use_default_headers=False,
            headers=headers,
            data=body,
        ) as resp:
            data = json.loads(await resp.read())

        frag = data["html"]
        if not frag:
            return await queue.resolve(ctx)

        if frag == "You need to sign in.":
            await ctx.send("Post requires authentication.")
            return await queue.resolve(ctx)

        if frag == "Error occurred.":
            await ctx.send("Poipiku reported a generic error.")
            return await queue.resolve(ctx)

        if frag == "Password is incorrect.":

            def check(m: Message):
                return (
                    (r := m.reference) is not None
                    and r.message_id == msg.id
                    and m.author.id == ctx.author.id
                )

            async def clean():
                if do_clean:
                    for msg in to_clean:
                        await msg.delete()

            assert isinstance(ctx.me, discord.Member)
            do_clean = await self.should_cleanup(ctx.message, ctx.me)

            delete_after = 10 if do_clean else None

            msg = await ctx.reply(
                "Post requires a password. Reply to this message with the password.",
                mention_author=True,
            )
            to_clean = [msg]

            while True:
                try:
                    reply = await ctx.bot.wait_for("message", check=check, timeout=60)
                except asyncio.TimeoutError:
                    await ctx.send(
                        "Poipiku password timeout expired.", delete_after=delete_after
                    )
                    await clean()
                    return await queue.resolve(ctx)

                to_clean.append(reply)

                body["PAS"] = reply.content

                async with self.get(
                    "https://poipiku.com/f/ShowAppendFileF.jsp",
                    method="POST",
                    use_default_headers=False,
                    headers=headers,
                    data=body,
                ) as resp:
                    data = json.loads(await resp.read())

                frag = data["html"]

                if frag == "Password is incorrect.":
                    msg = await reply.reply(
                        "Incorrect password. Try again, replying to this message.",
                        mention_author=True,
                    )
                    to_clean.append(msg)
                else:
                    await clean()
                    break

        root = html.document_fromstring(frag, self.parser)

        for img in root.xpath(".//img"):
            src = img.get("src")
            src = src.removesuffix("_640.jpg").replace("//img.", "//img-org.")
            src = f"https:{src}"
            queue.push_file(src, headers=refer)

        return await queue.resolve(ctx)

    async def display_bsky_images(
        self, ctx: CrosspostContext, repo: str, rkey: str
    ) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"bsky: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {repo}/{rkey}"
        )

        xrpc_url = BSKY_XRPC_FMT.format(repo, rkey)
        async with self.get(xrpc_url, use_default_headers=False) as resp:
            data = await resp.json()

        post = data["value"]

        if not (images := post.get("embed", {}).get("images")):
            return False

        did = data["uri"].removeprefix("at://").partition("/")[0]

        post_link = f"https://bsky.app/profile/{repo}/post/{rkey}"
        queue = FragmentQueue(ctx, post_link)

        for image in images:
            image = image["image"]
            image_id = image["ref"]["$link"]
            url = f"https://cdn.bsky.app/img/feed_fullsize/plain/{did}/{image_id}@jpeg"
            filename = f"{image_id}.jpeg"
            queue.push_file(url, filename=filename)

        if text := post["text"]:
            queue.push_text(f">>> {text}")

        return await queue.resolve(ctx)

    async def display_paheal_images(self, ctx: CrosspostContext, post: str) -> bool:
        link = f"https://rule34.paheal.net/post/view/{post}"

        assert ctx.guild is not None
        self.logger.info(
            f"paheal: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        async with self.get(link, use_default_headers=False) as resp:
            root = html.document_fromstring(await resp.read(), self.parser)

        img = root.xpath(PAHEAL_IMG_SELECTOR)[0]
        url = img.get("src")
        mime = img.get("data-mime").partition("/")[2]
        filename = f"{post}.{mime}"

        queue = FragmentQueue(ctx, link)

        queue.push_file(url, filename=filename)

        if source := root.xpath(PAHEAL_SOURCE_SELECTOR):
            queue.push_text(source[0].get("href"), force=True)

        return await queue.resolve(ctx)

    async def display_furaffinity_images(
        self, ctx: CrosspostContext, sub_id: str
    ) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"furaffinity: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {sub_id}"
        )

        link = f"https://www.fxraffinity.net/view/{sub_id}?full"
        async with self.get(
            link, error_for_status=False, allow_redirects=False
        ) as resp:
            root = html.document_fromstring(await resp.read(), self.parser)

        queue = FragmentQueue(ctx, link)

        url = root.xpath(OG_IMAGE)[0].get("content")
        queue.push_file(url)

        title = root.xpath(OG_TITLE)[0].get("content")
        desc = root.xpath(OG_DESCRIPTION)[0].get("content")
        queue.push_text(f"**{title}**")
        queue.push_text(f">>> {desc}")

        return await queue.resolve(ctx)

    async def display_ygal_images(self, ctx: CrosspostContext, gal_id: str) -> bool:
        assert ctx.guild is not None

        self.logger.info(
            f"ygal: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {gal_id}"
        )

        link = f"https://old.y-gallery.net/view/{gal_id}/"

        async with self.get(
            link, use_default_headers=False, headers=self.ygal_headers
        ) as resp:
            root = html.document_fromstring(await resp.read(), self.parser)

        img = root.xpath(YGAL_IMG_SELECTOR)[0]
        m = YGAL_FULLSIZE_EXPR.match(img.get("onclick"))
        assert m is not None
        link = m["link"]

        queue = FragmentQueue(ctx, link)
        queue.push_file(link, headers={"Referer": link})

        comment = html.tostring(root.xpath(YGAL_TEXT_SELECTOR)[0], encoding=str)
        assert isinstance(comment, str)
        if title := img.get("alt"):
            queue.push_text(f"**{title}**")
        comment = comment.strip()
        comment = comment.removeprefix('<div class="commentData">')
        comment = comment.removesuffix("</div>")
        comment = re.sub(r" ?<img[^>]*> ?", "", comment)
        if comment := translate_markdown(comment).strip():
            queue.push_text(f">>> {comment}")

        return await queue.resolve(ctx)

    async def display_pillowfort_images(self, ctx: CrosspostContext, link: str) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"pillowfort: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {link}"
        )

        async with self.get(link) as resp:
            root = html.document_fromstring(await resp.read(), self.parser)

        if not (images := root.xpath(OG_IMAGE)):
            return False

        images.reverse()

        max_pages = await self.get_max_pages(ctx)
        num_images = len(images)
        if max_pages == 0:
            max_pages = num_images

        pages_remaining = num_images - max_pages
        images = images[:max_pages]

        headers = {"Referer": link}

        for image in images:
            url = image.get("content").replace("_small.png", ".png")
            msg = await self.send(ctx, url, headers=headers)
            if too_large(msg):
                await ctx.send(url)

        if await self.should_post_text(ctx):
            title = html_unescape(root.xpath(OG_TITLE)[0].get("content"))
            desc = html_unescape(root.xpath(OG_DESCRIPTION)[0].get("content"))

            await ctx.send(f"**{title}**\n>>> {desc}", suppress_embeds=True)

        if pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            message = f"{pages_remaining} more image{s} at <{link}>"
            await ctx.send(message)

        return True

    async def display_yt_community_images(
        self, ctx: CrosspostContext, post_id: str
    ) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"yt_community: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {post_id}"
        )

        link = f"https://youtube.com/post/{post_id}"

        async with self.get(link) as resp:
            root = html.document_fromstring(await resp.read(), self.parser)

        if not (script := root.xpath(YT_SCRIPT_SELECTOR)):
            return False

        data = json.loads(f"{{{script[0].text.partition('{')[-1].rpartition(';')[0]}")

        # jesus christ
        tab = data["contents"]["twoColumnBrowseResultsRenderer"]["tabs"][0]
        section = tab["tabRenderer"]["content"]["sectionListRenderer"]["contents"][0]
        item = section["itemSectionRenderer"]["contents"][0]
        post = item["backstagePostThreadRenderer"]["post"]["backstagePostRenderer"]

        if not (attachment := post.get("backstageAttachment")):
            return False

        images = attachment.get("postMultiImageRenderer", {}).get("images", [])

        if not images:
            images = [attachment]

        posted = False
        for image in images:
            if not (renderer := image.get("backstageImageRenderer")):
                continue

            thumbs = renderer["image"]["thumbnails"]
            img: str = max(thumbs, key=lambda t: t["width"])["url"]

            ext = None
            async with self.get(img, method="HEAD") as resp:
                if (disp := resp.content_disposition) and (name := disp.filename):
                    ext = name.rpartition(".")[-1]

            ext = ext or "jpeg"

            if ext == "webp":
                proc = await asyncio.create_subprocess_exec(
                    "magick",
                    "convert",
                    img,
                    "gif:-",
                    stderr=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                )
                filename = f"{post_id}.gif"

                try:
                    stdout = await try_wait_for(proc)
                except asyncio.TimeoutError:
                    await ctx.send("Gif took too long to process.")
                    await self.send(ctx, img, filename=f"{post_id}.{ext}")
                else:
                    gif = BytesIO(stdout)
                    gif.seek(0)
                    file = File(gif, filename)
                    await ctx.send(file=file)
            else:
                await self.send(ctx, img, filename=f"{post_id}.{ext}")
            posted = True

        if (
            posted
            and await self.should_post_text(ctx)
            and (frags := post["contentText"].get("runs"))
        ):
            text = "".join(frag.get("text", "") for frag in frags)
            await ctx.send(f">>> {text}", suppress_embeds=True)

        return posted

    async def display_e621_images(self, ctx: CrosspostContext, post_id: str) -> bool:
        assert ctx.guild is not None
        self.logger.info(
            f"e621: {ctx.guild.id}/{ctx.channel.id}/{ctx.message.id}: {post_id}"
        )
        params = {"tags": f"id:{post_id}"}
        if self.e621_key:
            auth_slug = b64encode(f"{self.e621_user}:{self.e621_key}".encode()).decode()
            headers = {"Authorization": f"Basic {auth_slug}"}
        else:
            headers = {}
        api_url = "https://e621.net/posts.json"
        async with ctx.bot.get(api_url, params=params, headers=headers) as resp:
            data = await resp.json()
        try:
            post = data["posts"][0]
        except IndexError:
            raise ResponseError(404, api_url)

        await self.send(ctx, post["file"]["url"])

        if (text := post.get("description")) and await self.should_post_text(ctx):
            await ctx.send(f">>> {text}")

        if sources := post.get("sources"):
            await ctx.send(sources[-1], suppress_embeds=True)

        return True

    @commands.group(invoke_without_command=True, usage="")
    @is_owner_or(manage_guild=True)
    async def crosspost(self, ctx: BContext, argument: str = None, *_):
        """Change image crosspost settings.

        Each subcommand takes, in addition to the configuration value, an optional \
target, which specifies a channel or category to apply the setting to, instead of \
applying it to the guild as a whole."""
        if argument is not None:
            await ctx.send(f"No such configuration option: {argument}")
        else:
            await ctx.send("Missing configuration option.")

    @crosspost.command()
    async def auto(
        self,
        ctx: BContext,
        enabled: bool,
        *,
        target: ConfigTarget = None,
    ):
        """Enable or disable automatic crossposting."""
        guild = ctx.guild
        assert guild is not None
        settings = Settings(auto=enabled)
        await self.db.set_settings(guild.id, target.id if target else 0, settings)
        fmt = "en" if enabled else "dis"
        message = f"Crossposting images {fmt}abled"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command(hidden=True)
    async def mode(self, ctx: BContext, mode: str, *, _: str):
        """Setting crosspost mode is no longer supported."""
        await ctx.send("Setting crosspost mode is no longer supported.")

    @crosspost.command()
    async def pages(
        self,
        ctx: BContext,
        max_pages: int,
        *,
        target: ConfigTarget = None,
    ):
        """Set the maximum number of images to send.

        Set to 0 for no limit."""
        guild = ctx.guild
        assert guild is not None
        settings = Settings(max_pages=max_pages)
        await self.db.set_settings(guild.id, target.id if target else 0, settings)
        message = f"Max crosspost pages set to {max_pages}"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command(aliases=["suppress"])
    async def cleanup(
        self,
        ctx: BContext,
        enabled: bool,
        *,
        target: ConfigTarget = None,
    ):
        """Toggle automatic embed removal."""
        guild = ctx.guild
        assert guild is not None
        settings = Settings(cleanup=enabled)
        await self.db.set_settings(guild.id, target.id if target else 0, settings)
        fmt = "en" if enabled else "dis"
        message = f"Cleaning up embeds {fmt}abled"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command(aliases=["context"])
    async def text(
        self,
        ctx: BContext,
        enabled: bool,
        *,
        target: ConfigTarget = None,
    ):
        """Toggle crossposting of text context."""
        guild = ctx.guild
        assert guild is not None
        settings = Settings(text=enabled)
        await self.db.set_settings(guild.id, target.id if target else 0, settings)
        fmt = "en" if enabled else "dis"
        message = f"Crossposting text context {fmt}abled"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command()
    async def clear(self, ctx: BContext, *, target: ConfigTarget = None):
        """Clear crosspost settings.

        If no channel is specified, will clear all crosspost settings for the server."""
        if target is None:
            guild = ctx.guild
            assert guild is not None
            await self.db.clear_settings_all(guild.id)
            where = "this server"
        else:
            await self.db.clear_settings(target.guild.id, target.id)
            where = str(target)
        await ctx.send(f"Crosspost settings overrides cleared for {where}.")

    @crosspost.group(invoke_without_command=True)
    async def blacklist(self, ctx: BContext, site: str = ""):
        """Manage site blacklist for this server.

        To view all possible sites, run `blacklist list all`.
        """
        if site:
            try:
                site = await Site().convert(ctx, site)
            except BadArgument:
                raise
            else:
                await self.blacklist_add(ctx, site)
        else:
            await self.blacklist_list(ctx)

    @blacklist.command(name="add")
    async def blacklist_add(
        self, ctx: BContext, site: str = commands.param(converter=Site)
    ):
        """Add a site to the blacklist.

        Shortcut: `crosspost blacklist <site>`."""
        guild = ctx.guild
        assert guild is not None
        if await self.db.add_blacklist(guild.id, site):
            await ctx.send(f"Site {site} blacklisted.")
        else:
            await ctx.send(f"Site {site} already blacklisted.")

    @blacklist.command(name="remove", aliases=["del", "rm"])
    async def blacklist_remove(
        self, ctx: BContext, site: str = commands.param(converter=Site)
    ):
        """Remove a site from the blacklist."""
        guild = ctx.guild
        assert guild is not None
        if await self.db.del_blacklist(guild.id, site):
            await ctx.send(f"Site {site} removed from blacklist.")
        else:
            await ctx.send(f"Site {site} not in blacklist.")

    @staticmethod
    def blacklist_list_msg(blacklist: set[str]) -> str:
        if blacklist:
            return f"Currently blacklisted sites:\n{'\n'.join(sorted(blacklist))}"
        else:
            return "No sites are currently blacklisted."

    @blacklist.group(name="list", aliases=["get", "info"], invoke_without_command=True)
    async def blacklist_list(self, ctx: BContext):
        """List currently blacklisted sites.

        To view all sites, run `blacklist list all`."""
        guild = ctx.guild
        assert guild is not None
        blacklist = await self.db.get_blacklist(guild.id)
        await ctx.send(self.blacklist_list_msg(blacklist))

    @blacklist_list.command(name="all")
    async def blacklist_list_all(self, ctx: BContext):
        """List all sites and whether they're blacklisted."""
        guild = ctx.guild
        assert guild is not None
        blacklist = await self.db.get_blacklist(guild.id)
        list_msg = self.blacklist_list_msg(blacklist)
        if sites_left := set(HANDLER_DICT) - blacklist:
            left_msg = "\n".join(sorted(sites_left))
        else:
            left_msg = "... none...?"
        await ctx.send("\n".join([list_msg, "Sites you could blacklist:", left_msg]))

    @crosspost.command()
    async def info(self, ctx: BContext, *, target: ConfigTarget = None):
        """Get info on crosspost settings.

        If no channel is specified, will get info for the current channel."""
        if target is None:
            assert isinstance(ctx.channel, ConfigTarget)
            target = ctx.channel

        guild = ctx.guild
        assert guild is not None

        guild_id = guild.id

        guild_conf = await self.db._get_settings(guild_id, 0)
        final_conf = Settings()
        final_conf = final_conf.apply(guild_conf)
        msg = f"{guild.name}: {str(guild_conf) or '(none)'}"

        category = getattr(target, "category", None)
        if category is None and isinstance(target, CategoryChannel):
            category = target
        if category is not None:
            cat_conf = await self.db._get_settings(guild_id, category.id)
            final_conf = final_conf.apply(cat_conf)
            msg = f"{msg}\n{category.name}: {str(cat_conf) or '(none)'}"

        if target is not category:
            if isinstance(target, Thread):
                parent = await guild.fetch_channel(target.parent_id)
                assert isinstance(parent, ConfigTarget)
                target = parent
            chan_conf = await self.db._get_settings(guild_id, target.id)
            final_conf = final_conf.apply(chan_conf)
            msg = f"{msg}\n{target.name}: {str(chan_conf) or '(none)'}"

        msg = f"{msg}\nEffective: {str(final_conf) or '(none)'}"
        await ctx.send(msg)

    async def subcommand_error(self, ctx: BContext, e: Exception):
        if isinstance(e, BadUnionArgument):
            inner = e.errors[0]
            assert isinstance(inner, ChannelNotFound)
            await ctx.send(
                f"Could not resolve `{inner.argument}`"
                " as a category, channel, or thread."
            )
        else:
            await ctx.bot.handle_error(ctx, e)

    async def blacklist_error(self, ctx: BContext, e: Exception):
        if isinstance(e, (commands.BadArgument, commands.ConversionError)):
            await ctx.send(
                "Invalid site. "
                f"To list all sites, run {ctx.prefix}crosspost blacklist list all"
            )
        else:
            await ctx.bot.handle_error(ctx, e)

    for subcommand in crosspost.walk_commands():
        subcommand.on_error = subcommand_error

    blacklist.on_error = blacklist_error
    for subcommand in blacklist.walk_commands():
        subcommand.on_error = blacklist_error

    async def _post(self, ctx: CrosspostContext, *, force=False):
        message = ctx.message
        task = asyncio.create_task(self.process_links(ctx, force=force))
        self.ongoing_tasks[message.id] = task
        try:
            await asyncio.wait_for(task, None)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            raise e
        finally:
            del self.ongoing_tasks[message.id]

    @commands.command()
    async def post(self, ctx: BContext, *flags: PostFlags, _: str | None):
        """Embed images in the given links regardless of the auto setting.

        Put text=true or pages=X after post to change settings for this message only."""
        new_ctx = await self.bot.get_context(ctx.message, cls=CrosspostContext)
        pages = None
        text = None
        for flag in flags:
            if flag.pages is not None:
                pages = flag.pages
            if flag.text is not None:
                text = flag.text
        self.db.overrides[ctx.message.id] = Settings(max_pages=pages, text=text)
        try:
            await self._post(new_ctx, force=True)
        finally:
            del self.db.overrides[ctx.message.id]

    @commands.command(aliases=["_"])
    async def nopost(self, ctx: BContext, *, _: str = ""):
        """Ignore links in the following message.

        You can also use ||spoiler tags|| to achieve the same thing."""
        pass


HANDLER_DICT: dict[
    str,
    tuple[
        re.Pattern,
        Callable[[Crosspost, CrosspostContext, str], Awaitable[bool]],
    ],
] = {
    site: (expr, getattr(Crosspost, f"display_{site}_images"))
    for site, expr in HANDLER_EXPR
}


async def setup(bot: BeattieBot):
    await bot.add_cog(Crosspost(bot))
