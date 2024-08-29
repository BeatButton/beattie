from __future__ import annotations

import asyncio
from datetime import datetime
import logging
from io import BytesIO
from sys import getsizeof
from typing import TYPE_CHECKING, Any

import aiohttp
import toml
from lxml import etree, html
from tldextract import TLDExtract

import discord
from discord import CategoryChannel, Message, Thread
from discord.ext import commands
from discord.ext.commands import BadArgument, BadUnionArgument, ChannelNotFound, Cog
from discord.utils import format_dt

from beattie.utils.aioutils import squash_unfindable
from beattie.utils.checks import is_owner_or
from beattie.utils.etc import GB, display_bytes, spoiler_spans
from beattie.utils.exceptions import ResponseError
from beattie.utils.type_hints import GuildMessageable
from beattie.utils.contextmanagers import get

from .converters import PostFlags, Site as SiteConverter
from .context import CrosspostContext
from .database import Database, Settings
from .queue import FragmentQueue
from .sites import SITES, Site

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext


QUEUE_CACHE_SIZE: int = 1 * GB

ConfigTarget = GuildMessageable | CategoryChannel


class Crosspost(Cog):
    """Crossposts images from tweets and other social media"""

    bot: BeattieBot

    sites: list[Site]

    ongoing_tasks: dict[int, asyncio.Task]
    queue_cache: dict[tuple[str, ...], FragmentQueue]

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
        if (queue_cache := bot.extra.get("crosspost_queue_cache")) is not None:
            self.queue_cache = queue_cache
        else:
            self.queue_cache = {}
            bot.extra["crosspost_queue_cache"] = self.queue_cache
        self.tldextract = TLDExtract(suffix_list_urls=())
        self.logger = logging.getLogger(__name__)
        self.sites = [cls(self) for cls in SITES]

    async def cog_load(self):
        self.session = aiohttp.ClientSession()

        await self.db.async_init()

        for site in self.sites:
            await site.load()

    async def cog_unload(self):
        await self.session.close()
        for site in self.sites:
            await site.unload()

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
    ) -> tuple[bytes, str | None]:
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
        return img.getvalue(), filename

    async def process_links(
        self,
        ctx: CrosspostContext,
        *,
        force: bool = False,
        ranges: list[tuple[int, int]] = None,
    ):
        if guild := ctx.guild:
            assert isinstance(ctx.me, discord.Member)
            do_suppress = ctx.channel.permissions_for(ctx.me).manage_messages
            guild_id = guild.id
        else:
            do_suppress = False
            guild_id = 0

        if force or guild is None:
            blacklist = set()
        else:
            blacklist = await self.db.get_blacklist(guild_id)

        content = ctx.message.content
        sspans = spoiler_spans(content)
        for site in self.sites:
            name = site.name
            if name in blacklist:
                continue
            for m in site.pattern.finditer(content):
                ms, mt = m.span()
                spoiler = any(ms < st and ss < mt for ss, st in sspans)
                args = m.groups()
                link = content[ms:mt]
                if not args:
                    args = (link,)
                args = tuple(map(str.strip, args))
                key = (name, *args)
                logloc = f"{guild_id}/{ctx.channel.id}/{ctx.message.id}"
                if queue := self.queue_cache.get(key):
                    if queue.fragments:
                        self.logger.info(f"cache hit: {logloc}: {name} {args}")
                    coro = queue.perform(ctx, spoiler=spoiler, ranges=ranges)
                else:
                    self.queue_cache[key] = queue = FragmentQueue(ctx, link)
                    try:
                        await site.handler(ctx, queue, *args)
                    except ResponseError as e:
                        self.queue_cache.pop(key, None)
                        if e.code == 404:
                            await ctx.send("Post not found.")
                        else:
                            await ctx.bot.handle_error(ctx, e)
                        return
                    except Exception as e:
                        self.queue_cache.pop(key, None)
                        await ctx.bot.handle_error(ctx, e)
                        return
                    else:
                        if queue.fragments:
                            self.logger.info(f"{name}: {logloc}: {link}")
                        coro = queue.resolve(ctx, spoiler=spoiler, ranges=ranges)

                if await coro and do_suppress:
                    await squash_unfindable(ctx.message.edit(suppress=True))
                    do_suppress = False

                self.evict_cache()

    def evict_cache(self):
        size = sum(map(getsizeof, self.queue_cache.values()))
        if size <= QUEUE_CACHE_SIZE:
            return

        queues = sorted(
            self.queue_cache.items(), key=lambda kv: kv[1].last_used, reverse=True
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
            and (sent_messages := self.db._message_cache.get(message.id))
            and (guild := message.guild)
            and message.channel.permissions_for(guild.me).manage_messages
        ):
            return

        for message_id in sent_messages:
            try:
                msg = await message.channel.fetch_message(message_id)
            except discord.NotFound:
                pass
            except discord.Forbidden:
                return
            else:
                if msg.embeds or msg.attachments:
                    break
        else:
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
            await task
            if messages:
                await delete_messages(messages)
                messages_deleted = True
        if messages_deleted:
            await self.db.del_sent_messages(message_id)

    async def get_max_pages(self, ctx: BContext) -> int:
        settings = await self.db.get_effective_settings(ctx.message)
        max_pages = settings.max_pages
        if max_pages is None:
            max_pages = 10
        return max_pages

    async def should_post_text(self, ctx: BContext) -> bool:
        settings = await self.db.get_effective_settings(ctx.message)
        return bool(settings.text)

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
        enabled: bool,
        *,
        _: str = "",
    ):
        """Toggle automatic embed removal."""
        await ctx.send("Setting crosspost cleanup state is no longer supported.")

    @crosspost.command(aliases=["context"])
    async def text(
        self,
        ctx: BContext,
        enabled: bool,
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

    @crosspost.group(invoke_without_command=True)
    @commands.check(lambda ctx: ctx.guild is not None)
    async def blacklist(self, ctx: BContext, site: str = ""):
        """Manage site blacklist for this server.

        To view all possible sites, run `blacklist list all`.
        """
        if site:
            try:
                site = await SiteConverter().convert(ctx, site)
            except BadArgument:
                raise
            else:
                await self.blacklist_add(ctx, site)
        else:
            await self.blacklist_list(ctx)

    @blacklist.command(name="add")
    async def blacklist_add(
        self, ctx: BContext, site: str = commands.param(converter=SiteConverter)
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
        if sites_left := {site.name for site in self.sites} - blacklist:
            left_msg = "\n".join(sorted(sites_left))
        else:
            left_msg = "... none...?"
        await ctx.send("\n".join([list_msg, "Sites you could blacklist:", left_msg]))

    @crosspost.command()
    async def info(self, ctx: BContext, *, target: ConfigTarget = None):
        """Get info on crosspost settings.

        If no channel is specified, will get info for the current channel."""
        if guild := ctx.guild:
            if target is None:
                assert isinstance(ctx.channel, ConfigTarget)
                target = ctx.channel
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
        elif target is not None:
            msg = "No targets allowed in DM."
        else:
            conf = await self.db._get_settings(0, ctx.channel.id)
            msg = f"DM settings: {str(conf) or '(none)'}"
        await ctx.send(msg)

    @crosspost.command()
    async def stats(self, ctx: BContext):
        queues = self.queue_cache.values()
        memory = sum(map(getsizeof, queues))
        length = sum(len(queue.fragments) > 0 for queue in queues)
        if stamp := min((queue.last_used for queue in queues), default=None):
            oldest = format_dt(datetime.fromtimestamp(stamp), style="R")
        else:
            oldest = "(none)"

        embed = (
            discord.Embed()
            .add_field(name="Memory Used", value=display_bytes(memory))
            .add_field(name="Posts Cached", value=f"{length}")
            .add_field(name="Oldest Post", value=str(oldest))
        )

        await ctx.send(embed=embed)

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

    async def _post(
        self,
        ctx: CrosspostContext,
        *,
        force=False,
        ranges: list[tuple[int, int]] = None,
    ):
        message = ctx.message
        task = asyncio.create_task(self.process_links(ctx, force=force, ranges=ranges))
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

        override = Settings(text=text)
        ranges = None
        if isinstance(pages, int):
            override.max_pages = pages
        else:
            ranges = pages
        self.db.overrides[ctx.message.id] = override
        try:
            await self._post(new_ctx, force=True, ranges=ranges)
        finally:
            del self.db.overrides[ctx.message.id]

    @commands.command(aliases=["_"])
    async def nopost(self, ctx: BContext, *, _: str = ""):
        """Ignore links in the following message."""
        pass
