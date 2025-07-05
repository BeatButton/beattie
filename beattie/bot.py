from __future__ import annotations

import asyncio
import logging
import lzma
import os
import sys
import tarfile
import traceback
from asyncio import Task
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, overload

import httpx
import toml

from discord import AllowedMentions, Game, Guild, Intents, Message
from discord.ext import commands
from discord.ext.commands import Bot, Context, when_mentioned_or

from beattie.config import Config
from beattie.context import BContext
from beattie.help import BHelp
from beattie.utils import contextmanagers, exceptions
from beattie.utils.aioutils import do_every

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable

    import asyncpg

    from discord.http import HTTPClient

C = TypeVar("C", bound=Context)


class Shared:
    bot_ids: set[int]
    bots: list[BeattieBot]
    archive_task: Task[Any] | None
    logger: logging.Logger
    session: httpx.AsyncClient
    pool: asyncpg.Pool
    extra: dict[str, Any]
    uptime: datetime

    def __init__(
        self,
        prefixes: tuple[str, ...],
        pool: asyncpg.Pool,
        debug: bool,
    ):
        with open("config/config.toml") as file:
            data = toml.load(file)

        self.prefixes = prefixes
        self.loglevel = data.get("loglevel", logging.WARNING)
        self.debug = debug
        self.pool = pool
        self.config = Config(self)
        self.uptime = datetime.now().astimezone()
        self.extra = {}
        if debug:
            self.loglevel = logging.DEBUG
            self.archive_task = None
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(
                logging.Formatter("%(levelname)s:%(name)s: %(message)s")
            )
            logging.getLogger("beattie").addHandler(handler)
        else:
            self.archive_task = do_every(60 * 60 * 24, self.swap_logs)
        self.new_logger()

    async def async_init(self):
        self.session = httpx.AsyncClient(follow_redirects=True, timeout=None)
        await self.config.async_init()

    async def prefix_func(self, bot: BeattieBot, message: Message) -> Iterable[str]:
        prefix = self.prefixes
        if guild := message.guild:
            guild_conf = await bot.shared.config.get_guild(guild.id)
            if guild_pre := guild_conf.get("prefix"):
                prefix = prefix + (guild_pre,)
        return when_mentioned_or(*prefix)(bot, message)

    async def close(self):
        if close := getattr(self, "_close", None):
            await close.wait()
            return

        self._close = asyncio.Event()

        await self.session.aclose()
        await self.pool.close()
        if self.archive_task is not None:
            self.archive_task.cancel()
        for bot in self.bots:
            asyncio.create_task(bot.close())

        self._close.set()

    def swap_logs(self, new: bool = True) -> Awaitable[None]:
        if new:
            self.new_logger()
        return asyncio.to_thread(self.archive_logs)

    def new_logger(self):
        logger = logging.getLogger()
        logger.setLevel(self.loglevel)
        now = datetime.now().astimezone()
        if self.debug:
            pre = "debug"
        else:
            pre = "discord"
        filename = now.strftime(f"{pre}%Y%m%d%H%M.log")
        handler = logging.FileHandler(filename=filename, encoding="utf-8", mode="w")
        handler.setFormatter(
            logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
        )
        logger.addHandler(handler)
        self.logger = logger

    def archive_logs(self):
        logname = "logs.tar"
        if os.path.exists(logname):
            mode = "a"
        else:
            mode = "w"
        # get all logfiles but newest
        old_logs = sorted(Path(".").glob("discord*.log"), key=os.path.getmtime)[:-1]
        with tarfile.open(logname, mode) as tar:
            for log in old_logs:
                name = f"{log.name}.xz"
                with open(log, "rb") as r, lzma.open(name, "w") as w:
                    for line in r:
                        w.write(line)
                tar.add(name)
                os.unlink(name)
                log.unlink()


class BeattieBot(Bot):
    """A very cute robot boy"""

    command_ignore = (commands.CommandNotFound, commands.CheckFailure)
    general_ignore = (ConnectionResetError,)

    http: HTTPClient
    shared: Shared

    def __init__(
        self,
        shared: Shared,
    ):
        self.shared = shared
        self.logger = logging.getLogger(__name__)
        self.pool = shared.pool
        self.config = shared.config
        self.session = shared.session
        self.extra = shared.extra
        self.uptime = shared.uptime

        super().__init__(
            shared.prefix_func,
            activity=Game(name=f"{shared.prefixes[0]}help"),
            case_insensitive=True,
            help_command=BHelp(),
            intents=Intents.all(),
            allowed_mentions=AllowedMentions.none(),
            log_handler=None,
        )

    async def setup_hook(self):
        cogs = Path(__file__).parent / "cogs"
        extensions = [f"beattie.cogs.{f.stem}" for f in cogs.glob("*.py")]
        extensions.append("beattie.cogs.crosspost")
        extensions.append("jishaku")
        for extension in extensions:
            try:
                await self.load_extension(extension, package="cogs")
            except Exception as e:
                print(
                    "Failed to load extension",
                    extension,
                    file=sys.stderr,
                )
                traceback.print_exception(type(e), e, e.__traceback__)

    async def close(self):
        await super().close()
        await self.shared.close()

    async def handle_error(self, ctx: Context, e: BaseException):
        if isinstance(e, (commands.CommandInvokeError, commands.ExtensionFailed)):
            e = e.original
        if isinstance(e, commands.MissingRequiredArgument):
            await ctx.send("Missing required arguments.")
        elif isinstance(e, commands.BadArgument):
            args = e.args
            if len(args) > 1:
                await ctx.send(f"{args[0]}: {', '.join(args[1:])}")
            elif args:
                await ctx.send(f"Bad argument: {args[0]}")
            else:
                await ctx.send("Bad arguments.")
        elif isinstance(e, exceptions.ResponseError):
            await ctx.send(
                f"An HTTP request to <{e.url}> failed with error code {e.code}"
            )
        elif not isinstance(e, self.command_ignore):
            await ctx.send(f"{type(e).__name__}: {e}")
            if ctx.command is not None:
                message = f"An error occurred in {ctx.command.name}"
            else:
                message = (
                    f"An error occured in guild {ctx.guild} channel #{ctx.channel}"
                )
            self.logger.exception(message, exc_info=(type(e), e, e.__traceback__))
            raise e

    async def on_ready(self):
        user = self.user
        assert user is not None
        self.shared.bot_ids.add(user.id)
        print("Logged in as")
        print(user.name)
        print(user.id)
        print("------")

    async def on_guild_join(self, guild: Guild):
        user = self.user
        assert user is not None
        others = self.shared.bot_ids - {user.id}
        if any(m.id in others for m in guild.members):
            await guild.leave()

    @overload
    async def get_context(self, message: Message) -> BContext: ...

    @overload
    async def get_context(self, message: Message, *, cls: type[C]) -> C: ...

    def get_context(
        self, message: Message, *, cls: type[Context] = None
    ) -> Awaitable[Context]:
        return super().get_context(message, cls=cls or BContext)

    async def on_command_error(self, ctx: Context, e: Exception):
        if not hasattr(ctx.command, "on_error"):
            await self.handle_error(ctx, e)

    async def on_error(self, event_method: str, *args: Any, **kwargs: Any):
        _, e, _ = sys.exc_info()
        if isinstance(e, (commands.CommandInvokeError, commands.ExtensionFailed)):
            e = e.original
        if not isinstance(e, self.general_ignore):
            await super().on_error(event_method, *args, **kwargs)

    def get(self, *args: Any, **kwargs: Any) -> contextmanagers.get:
        return contextmanagers.get(self.session, *args, **kwargs)
