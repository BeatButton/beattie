from __future__ import annotations

import asyncio
import copy
import logging
import re
from datetime import datetime
from itertools import groupby
from sys import getsizeof
from typing import TYPE_CHECKING, Any

import aiohttp
import httpx
import toml
from lxml import etree, html
from tldextract import ExtractResult, TLDExtract

import discord
from discord import CategoryChannel, Message, Thread
from discord.ext import commands
from discord.ext.commands import BadUnionArgument, ChannelNotFound, Cog
from discord.utils import format_dt

from beattie.cogs.crosspost.exceptions import DownloadError
from beattie.cogs.crosspost.flaresolverr import FlareSolverr
from beattie.utils.checks import is_owner_or
from beattie.utils.contextmanagers import get
from beattie.utils.etc import GB, URL_EXPR, display_bytes, spoiler_spans
from beattie.utils.type_hints import GuildMessageable

from .context import CrosspostContext
from .converters import LanguageConverter, PostFlags
from .converters import Site as SiteConverter
from .database import Database, Settings
from .queue import FragmentQueue, Postable, QueueKwargs
from .sites import SITES, Site
from .translator import (
    DONT,
    DeeplTranslator,
    HybridTranslator,
    Language,
    LibreTranslator,
    Translator,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from beattie.bot import BeattieBot
    from beattie.context import BContext

    from .flaresolverr import Config as FsC


ConfigTarget = GuildMessageable | CategoryChannel

QUEUE_CACHE_SIZE: int = 1 * GB


def item_priority(item: Postable):
    match type(item).__name__:
        case "FileFragment" | "FallbackFragment":
            return 0
        case "EmbedFragment":
            return 1
        case "TextFragment":
            return 2
        case _:
            return 3


class Crosspost(Cog):
    """Crossposts images from tweets and other social media"""

    bot: BeattieBot

    sites: list[Site]

    fs_solver_url: str | None
    fs_proxy_url: str | None
    translator: Translator | None
    ongoing_tasks: dict[int, asyncio.Task[None]]
    queue_cache: dict[tuple[str, ...], FragmentQueue]
    cache_lock: asyncio.Lock
    session: httpx.AsyncClient

    def __init__(self, bot: BeattieBot):
        self.bot = bot
        self.db = Database(bot, self)
        self.parser = html.HTMLParser(encoding="utf-8")
        self.xml_parser = etree.XMLParser(encoding="utf-8")
        if (ongoing_tasks := bot.extra.get("crosspost_ongoing_tasks")) is not None:
            self.ongoing_tasks = ongoing_tasks
        else:
            self.ongoing_tasks = {}
            bot.extra["crosspost_ongoing_tasks"] = self.ongoing_tasks
        if (queue_cache := bot.extra.get("crosspost_queue_cache")) is not None:
            self.queue_cache = queue_cache
        else:
            self.queue_cache = {}
            bot.extra["crosspost_queue_cache"] = self.queue_cache
        if (session := bot.extra.get("crosspost_session")) is not None:
            self.session = session

        self.fs_solver_url = None
        self.fs_proxy_url = None

        try:
            with open("config/crosspost/flaresolverr.toml") as fp:
                fsconfig: FsC = toml.load(fp)  # pyright: ignore[reportAssignmentType]
                solver_url = fsconfig["solver"]
                proxy_url = fsconfig["proxy"]

        except (FileNotFoundError, KeyError):
            pass
        else:
            self.fs_solver_url = solver_url
            self.fs_proxy_url = proxy_url

        self.translator = None

        try:
            with open("config/translator.toml") as fp:
                data: dict[str, dict[str, str]] = toml.load(fp)

            libre = deepl = None
            if conf := data.get("libre"):
                libre = LibreTranslator(self, conf["url"], conf["key"])
            if conf := data.get("deepl"):
                deepl = DeeplTranslator(self, conf["url"], conf["key"])

            match libre, deepl:
                case None, None:
                    self.translator = None
                case libre, None:
                    self.translator = libre
                case None, deepl:
                    self.translator = deepl
                case libre, deepl:
                    self.translator = HybridTranslator(self, libre, deepl)

            if bot.shared.debug and libre is not None:
                self.translator = libre

        except FileNotFoundError:
            pass

        self._tldextract = TLDExtract()
        self.logger = logging.getLogger(__name__)
        self.sites = [cls(self) for cls in SITES]
        self.cache_lock = asyncio.Lock()

    async def cog_load(self):
        if not hasattr(self, "session"):
            self.session = httpx.AsyncClient(follow_redirects=True, timeout=None)
            self.bot.extra["crosspost_session"] = self.session

        await self.db.async_init()

        for site in self.sites:
            await site.load()

    async def cog_unload(self):
        for site in self.sites:
            await site.unload()

    def get(
        self,
        *urls: str,
        method: str = "GET",
        use_browser_ua: bool = False,
        session: httpx.AsyncClient = None,
        **kwargs: Any,
    ) -> get:
        if use_browser_ua:
            kwargs["headers"] = {
                **(kwargs.get("headers") or {}),
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:141.0)"
                " Gecko/20100101 Firefox/141.0",
            }
        return get(session or self.session, *urls, method=method, **kwargs)

    def flaresolverr(self) -> FlareSolverr:
        if self.fs_solver_url is None or self.fs_proxy_url is None:
            msg = "FlareSolverr config not set"
            raise RuntimeError(msg)
        return FlareSolverr(self, self.fs_solver_url, self.fs_proxy_url)

    async def tldextract(self, url: str) -> ExtractResult:
        return await asyncio.to_thread(self._tldextract, url)

    async def save(
        self,
        *img_urls: str,
        use_browser_ua: bool = True,
        headers: dict[str, str] = None,
    ) -> tuple[bytes, str | None]:
        headers = headers or {}
        filename = None
        async with self.get(
            *img_urls,
            use_browser_ua=use_browser_ua,
            headers=headers,
        ) as resp:
            if disp := resp.headers.get("Content-Disposition"):
                _, params = aiohttp.multipart.parse_content_disposition(disp)
                filename = params.get("filename")
            return resp.content, filename

    async def process_links(
        self,
        ctx: CrosspostContext,
        steps: Iterable[re.Match[str] | PostFlags],
        *,
        force: bool = False,
    ):
        steps = list(steps)
        if not any(isinstance(step, re.Match) for step in steps):
            return

        if guild := ctx.guild:
            do_suppress = ctx.channel.permissions_for(guild.me).manage_messages
            guild_id = guild.id
        else:
            do_suppress = False
            guild_id = 0

        if force or guild is None:
            blacklist = set()
        else:
            blacklist = await self.db.get_blacklist(guild_id)

        logloc = guild_id, ctx.channel.id, ctx.message.id
        settings = await self.db.get_effective_settings(ctx.message)
        self.logger.debug("process links: %s/%s/%s: %s", *logloc, settings)

        content = ctx.message.content
        sspans = spoiler_spans(content)

        queues: list[tuple[FragmentQueue, QueueKwargs]] = []
        new: set[FragmentQueue] = set()

        ranges = None
        for step in steps:
            if isinstance(step, PostFlags):
                settings = copy.copy(settings)
                if r := step.pages:
                    ranges = r
                if step.text is not None:
                    settings.text = step.text
                continue

            link = step.group(0)

            matches: list[tuple[re.Match[str], Site]] = []
            for site in self.sites:
                if site in blacklist:
                    continue
                if m := site.pattern.search(link):
                    matches.append((m, site))

            for m, site in matches:
                name = site.name
                ms, mt = step.span()
                spoiler = any(ms < st and ss < mt for ss, st in sspans)
                kwargs = QueueKwargs(
                    spoiler=spoiler,
                    force=force,
                    ranges=ranges,
                    settings=settings,
                )
                args = m.groups()
                if not args:
                    args = (link,)
                key = (name, *(a.strip() if a else "" for a in args))
                queue = self.queue_cache.get(key)
                if queue and queue.handle_task.done() and queue.handle_task.exception():
                    queue = None
                    self.queue_cache.pop(key, None)
                if queue:
                    if queue.fragments:
                        self.logger.info(
                            "cache hit: %s/%s/%s: %s %s",
                            *logloc,
                            name,
                            args,
                        )
                    queues.append((queue, kwargs))
                else:
                    if self.bot.shared.debug or name != "mastodon":
                        self.logger.info("began %s: %s/%s/%s: %s", name, *logloc, link)
                    queue = FragmentQueue(ctx, site, link, *args)
                    self.queue_cache[key] = queue
                    queues.append((queue, kwargs))
                    new.add(queue)

            for queue, _ in queues:
                self.bot.shared.create_task(queue.site.on_invoke(ctx, queue))
                try:
                    await queue.handle_task
                except Exception:
                    self.logger.exception(
                        "error: %s/%s/%s: %s %s ",
                        *logloc,
                        queue.site.name,
                        queue.link,
                    )
                    raise
                if queue in new and queue.fragments:
                    self.logger.info(
                        "%s: %s/%s/%s: %s",
                        queue.site.name,
                        *logloc,
                        queue.link,
                    )

        for _, batch in groupby(
            filter(lambda p: p[0].fragments, queues),
            lambda p: (p[0].site.name, p[0].author or object()),
        ):
            items: list[tuple[Postable, bool]] = []
            batch = list(batch)
            for queue, kwargs in batch:
                items.extend(
                    await queue.produce(
                        spoiler=kwargs["spoiler"],
                        ranges=kwargs["ranges"],
                        settings=kwargs["settings"],
                    ),
                )

            if len(batch) > 1:
                items.sort(key=lambda tup: item_priority(tup[0]))

            queue, kwargs = batch[0]
            try:
                embedded = await queue.present(
                    ctx,
                    items=items,
                    force=kwargs["force"],
                    settings=settings,
                )
            except DownloadError as e:
                queue = e.fragment.queue
                key = (queue.site.name, *queue.args)
                self.queue_cache.pop(key, None)
                raise e.source from None

            if embedded and do_suppress:
                ctx.bot.shared.create_task(ctx.message.edit(suppress=True))
                do_suppress = False

        ctx.bot.shared.create_task(self.try_evict())

    async def try_evict(self):
        if self.cache_lock.locked():
            return

        async with self.cache_lock:
            await asyncio.to_thread(self.evict_cache)

    def evict_cache(self):
        size = sum(map(getsizeof, self.queue_cache.values()))
        if size <= QUEUE_CACHE_SIZE:
            return

        queues = sorted(
            self.queue_cache.items(),
            key=lambda kv: kv[1].last_used,
            reverse=True,
        )

        while queues and size > QUEUE_CACHE_SIZE:
            key, queue = queues.pop()
            size -= getsizeof(queue)
            self.queue_cache.pop(key, None)

    @Cog.listener()
    async def on_message(self, message: Message):
        if message.author.bot:
            return
        guild = message.guild

        if guild and not message.channel.permissions_for(guild.me).send_messages:
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
        if not (
            message.embeds
            and (guild := message.guild)
            and message.channel.permissions_for(guild.me).manage_messages
            and (sent_messages := await self.db.get_sent_messages(message.id))
        ):
            return

        for message_id in sent_messages.message_ids:
            try:
                msg = await message.channel.fetch_message(message_id)
            except discord.NotFound:  # noqa: PERF203
                pass
            except discord.Forbidden:
                return
            else:
                if msg.embeds or msg.attachments:
                    break
        else:
            return

        await message.edit(suppress=True)

    async def delete_messages(self, channel_id: int, messages: list[int]):
        for message_id in messages:
            try:
                await self.bot.http.delete_message(channel_id, message_id)
            except discord.NotFound:  # noqa: PERF203
                pass
            except discord.Forbidden:
                return

    @Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        message_id = payload.message_id
        if await self.db.get_invoking_author_id(message_id):
            await self.db.del_sent_message(message_id)
            return

        if task := self.ongoing_tasks.get(message_id):
            task.cancel()
            try:
                await task
            except Exception:  # noqa: S110, this exception belongs to _post
                pass
        if messages := await self.db.get_sent_messages(message_id):
            await self.delete_messages(payload.channel_id, messages.message_ids)
            await self.db.del_sent_messages(message_id)

    @Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if str(payload.emoji) != "❌":
            return

        message_id = payload.message_id
        if not (author_id := await self.db.get_invoking_author_id(message_id)):
            return

        reactor_id = payload.user_id
        reactor = self.bot.get_user(reactor_id)
        if not reactor or reactor == self.bot.user:
            return

        if not (
            author_id == reactor_id
            or await self.bot.is_owner(reactor)
            or (guild_id := payload.guild_id) is None
            or (guild := self.bot.get_guild(guild_id))
            and (member := guild.get_member(reactor_id))
            and (channel := guild.get_channel(payload.channel_id))
            and channel.permissions_for(member).manage_messages
        ):
            return

        await self.delete_messages(payload.channel_id, [message_id])

    @commands.group()
    @is_owner_or(manage_guild=True)
    async def crosspost(self, ctx: BContext):
        """Change image crosspost settings.

        Each subcommand takes, in addition to the configuration value, an optional \
target, which specifies a channel or category to apply the setting to, instead of \
applying it to the guild as a whole."""
        if ctx.invoked_subcommand is None:
            if argument := ctx.subcommand_passed:
                await ctx.send(f"No such configuration option: {argument}")
            else:
                await ctx.send("Missing configuration option.")

    @crosspost.command()
    async def auto(
        self,
        ctx: BContext,
        enabled: bool,  # noqa: FBT001
        *,
        target: ConfigTarget = None,
    ):
        """Enable or disable automatic crossposting."""
        if guild := ctx.guild:
            guild_id = guild.id
            target_id = target.id if target else 0
        else:
            guild_id = 0
            if target is not None:
                await ctx.send("No targets allowed in DM.")
                return
            target_id = ctx.channel.id

        settings = Settings(auto=enabled)
        await self.db.set_settings(guild_id, target_id, settings)
        fmt = "en" if enabled else "dis"
        message = f"Crossposting images {fmt}abled"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command(hidden=True)
    async def mode(self, ctx: BContext, mode: str, *, _: str):  # noqa: ARG002
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
        if guild := ctx.guild:
            guild_id = guild.id
            target_id = target.id if target else 0
        else:
            guild_id = 0
            if target is not None:
                await ctx.send("No targets allowed in DM.")
                return
            target_id = ctx.channel.id
        settings = Settings(max_pages=max_pages)
        await self.db.set_settings(guild_id, target_id, settings)
        message = f"Max crosspost pages set to {max_pages}"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command(aliases=["suppress"], hidden=True)
    async def cleanup(
        self,
        ctx: BContext,
        enabled: bool,  # noqa: ARG002, FBT001
        *,
        _: str = "",
    ):
        """Toggle automatic embed removal."""
        await ctx.send("Setting crosspost cleanup state is no longer supported.")

    @crosspost.command(aliases=["context"])
    async def text(
        self,
        ctx: BContext,
        enabled: bool,  # noqa: FBT001
        *,
        target: ConfigTarget = None,
    ):
        """Toggle crossposting of text context."""
        if guild := ctx.guild:
            guild_id = guild.id
            target_id = target.id if target else 0
        else:
            guild_id = 0
            if target is not None:
                await ctx.send("No targets allowed in DM.")
                return
            target_id = ctx.channel.id
        settings = Settings(text=enabled)
        await self.db.set_settings(guild_id, target_id, settings)
        fmt = "en" if enabled else "dis"
        message = f"Crossposting text context {fmt}abled"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command(aliases=["lang", "translate"])
    async def language(
        self,
        ctx: BContext,
        language: Language = commands.param(converter=LanguageConverter),
        *,
        target: ConfigTarget = None,
    ):
        """Configure translation.

        Specify true/yes/on to translate text into English, false/no/off not to \
translate text, or a language name or code to translate text into that language."""
        if guild := ctx.guild:
            guild_id = guild.id
            target_id = target.id if target else 0
        else:
            guild_id = 0
            if target is not None:
                await ctx.send("No targets allowed in DM.")
                return
            target_id = ctx.channel.id
        settings = Settings(language=language)
        await self.db.set_settings(guild_id, target_id, settings)
        if language == DONT:
            message = "Translation disabled"
        else:
            message = f"Will translate to {language.name}"
        if target is not None:
            message = f"{message} in {target.mention}"
        await ctx.send(f"{message}.")

    @crosspost.command()
    async def clear(self, ctx: BContext, *, target: ConfigTarget = None):
        """Clear crosspost settings.

        If no channel is specified, will clear all crosspost settings for the server."""
        if target is None:
            if guild := ctx.guild:
                await self.db.clear_settings_all(guild.id)
                where = "this server"
            else:
                await self.db.clear_settings(0, ctx.channel.id)
                where = "this DM"
        else:
            await self.db.clear_settings(target.guild.id, target.id)
            where = str(target)
        await ctx.send(f"Crosspost settings overrides cleared for {where}.")

    @crosspost.group()
    @commands.check(lambda ctx: ctx.guild is not None)
    async def blacklist(self, ctx: BContext):
        """Manage site blacklist for this server.

        To view all possible sites, run `blacklist list all`.
        """
        if ctx.invoked_subcommand is None:
            if site := ctx.subcommand_passed:
                site = await SiteConverter().convert(ctx, site)
                await self.blacklist_add(ctx, site)
            else:
                await self.blacklist_list(ctx)

    @blacklist.command(name="add")
    async def blacklist_add(
        self,
        ctx: BContext,
        site: str = commands.param(converter=SiteConverter),
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
        self,
        ctx: BContext,
        site: str = commands.param(converter=SiteConverter),
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
        return "No sites are currently blacklisted."

    @blacklist.group(name="list", aliases=["get", "info"])
    async def blacklist_list(self, ctx: BContext):
        """List currently blacklisted sites.

        To view all sites, run `blacklist list all`."""
        if ctx.invoked_subcommand is None:
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
        if sites_left := {site.name for site in self.sites} - blacklist:
            left_msg = "\n".join(sorted(sites_left))
        else:
            left_msg = "... none...?"
        await ctx.send(f"{list_msg}\nSites you could blacklist:\n{left_msg}")

    @crosspost.command()
    async def info(self, ctx: BContext, _: str | None):
        """Get info on crosspost settings for the current channel."""
        final_conf = Settings()

        if guild := ctx.guild:
            target = ctx.channel
            assert isinstance(target, ConfigTarget)
            guild_id = guild.id

            guild_conf = await self.db._get_settings(guild_id, 0)
            final_conf = final_conf.apply(guild_conf)
            msg = f"{guild.name}: {guild_conf}"

            category = getattr(target, "category", None)
            if category is None and isinstance(target, CategoryChannel):
                category = target
            if category is not None:
                cat_conf = await self.db._get_settings(guild_id, category.id)
                final_conf = final_conf.apply(cat_conf)
                msg = f"{msg}\n{category.name}: {cat_conf}"

            if target is not category:
                if isinstance(target, Thread):
                    parent = await guild.fetch_channel(target.parent_id)
                    assert isinstance(parent, ConfigTarget)
                    target = parent
                chan_conf = await self.db._get_settings(guild_id, target.id)
                final_conf = final_conf.apply(chan_conf)
                msg = f"{msg}\n{target.name}: {chan_conf}"
        else:
            dm_conf = await self.db._get_settings(0, ctx.channel.id)
            final_conf = final_conf.apply(dm_conf)
            msg = f"DM settings: {dm_conf}"

        settings = await self.db.get_effective_settings(ctx.message)

        msg = f"{msg}\nEffective: {settings}"
        if settings != final_conf:
            msg = (
                f"{msg}\nCalculated: {final_conf}\n"
                "**Caculated differs from actual effective**! This is a bug!"
            )

        await ctx.send(msg)

    @crosspost.command()
    async def stats(self, ctx: BContext):
        queues = self.queue_cache.values()
        memory = await asyncio.to_thread(sum, map(getsizeof, queues))
        length = sum(len(queue.fragments) > 0 for queue in queues)
        if stamp := min((queue.last_used for queue in queues), default=None):
            oldest = format_dt(datetime.fromtimestamp(stamp), style="R")  # noqa: DTZ006
        else:
            oldest = "(none)"

        embed = (
            discord.Embed()
            .add_field(name="Memory Used", value=display_bytes(memory))
            .add_field(name="Posts Cached", value=f"{length}")
            .add_field(name="Oldest Post", value=str(oldest))
        )

        await ctx.send(embed=embed)

    @crosspost.command()
    @commands.is_owner()
    async def evict(
        self,
        ctx: BContext,
        target: str = None,
    ):
        """Evict posts from the cache. Optionally pass a site or a post to target."""
        count = 0

        if target is not None:
            matches = (
                (m, site) for site in self.sites if (m := site.pattern.search(target))
            )

            for m, site in matches:
                name = site.name
                args = m.groups()
                if not args:
                    args = (target,)
                key = (name, *(a.strip() if a else "" for a in args))
                if self.queue_cache.pop(key, None) is not None:
                    count += 1

        if count == 0:
            for key in list(self.queue_cache.keys()):
                if target is None or key[0] == target:
                    count += 1
                    self.queue_cache.pop(key, None)
        await ctx.send(f"Evicted {count}.")

    async def subcommand_error(self, ctx: BContext, e: Exception):
        if isinstance(e, BadUnionArgument):
            inner = e.errors[0]
            if isinstance(inner, ChannelNotFound):
                await ctx.send(
                    f"Could not resolve `{inner.argument}`"
                    " as a category, channel, or thread.",
                )
                return
        await ctx.bot.handle_error(ctx, e)

    async def blacklist_error(self, ctx: BContext, e: Exception):
        if isinstance(e, (commands.BadArgument, commands.ConversionError)):
            await ctx.send(
                "Invalid site. "
                f"To list all sites, run {ctx.prefix}crosspost blacklist list all",
            )
            return
        await ctx.bot.handle_error(ctx, e)

    for subcommand in crosspost.walk_commands():
        subcommand.on_error = subcommand_error

    blacklist.on_error = blacklist_error
    for subcommand in blacklist.walk_commands():
        subcommand.on_error = blacklist_error

    async def _post(
        self,
        ctx: CrosspostContext,
        *,
        force: bool = False,
    ):
        ctx.current_parameter = commands.parameter()
        matches = URL_EXPR.finditer(ctx.message.content)
        match = next(matches, None)
        steps: list[re.Match[str] | PostFlags] = []
        for arg in ctx.message.content.split():
            if match and match.group(0) in arg:
                steps.append(match)
                match = next(matches, None)
            elif flag := await PostFlags().convert(ctx, arg):
                steps.append(flag)
            elif m := URL_EXPR.match(f"https://{arg}"):
                steps.append(m)

        message_id = ctx.message.id
        coro = self.process_links(ctx, steps=steps, force=force)
        task = self.ongoing_tasks[message_id] = asyncio.create_task(coro)
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            ctx.bot.shared.create_task(ctx.message.add_reaction("⚠️"))
            raise
        finally:
            del self.ongoing_tasks[message_id]

    @commands.command()
    async def post(self, ctx: BContext):
        """Embed images in the given links regardless of the auto setting.

        Put text=true or pages=X after post to change settings for this message only."""
        new_ctx = await self.bot.get_context(ctx.message, cls=CrosspostContext)
        await self._post(new_ctx, force=True)

    @commands.command(aliases=["_"])
    async def nopost(self, ctx: BContext, *, _: str = ""):
        """Ignore links in the following message."""
