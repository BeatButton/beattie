from __future__ import annotations

import asyncio
import logging
import lzma
import os
import sys
import tarfile
from asyncio import Task
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Type, TypeVar, overload

import aiohttp
import toml
from asyncqlio.db import DatabaseInterface
from discord import AllowedMentions, Game, Intents, Message
from discord.ext import commands
from discord.ext.commands import Bot, Context, when_mentioned_or
from discord.http import HTTPClient

from config import Config
from context import BContext
from help import BHelp
from utils import contextmanagers, exceptions
from utils.aioutils import do_every

C = TypeVar("C", bound=Context)


class BeattieBot(Bot):
    """A very cute robot boy"""

    command_ignore = (commands.CommandNotFound, commands.CheckFailure)
    general_ignore = (ConnectionResetError,)

    archive_task: Optional[Task[Any]]
    http: HTTPClient
    session: aiohttp.ClientSession

    extra: dict[str, Any]

    def __init__(
        self,
        prefixes: tuple[str, ...],
        debug: bool = False,
    ):
        async def prefix_func(bot: Bot, message: Message) -> Iterable[str]:
            prefix = prefixes
            if guild := message.guild:
                guild_conf = await bot.config.get_guild(guild.id)  # type: ignore
                if guild_pre := guild_conf.get("prefix"):
                    prefix = prefix + (guild_pre,)
            return when_mentioned_or(*prefix)(self, message)

        help_command: commands.HelpCommand = BHelp()
        game = Game(name=f"{prefixes[0]}help")

        super().__init__(
            prefix_func,
            activity=game,
            case_insensitive=True,
            help_command=help_command,
            intents=Intents.all(),
            allowed_mentions=AllowedMentions.none(),
        )

        with open("config/config.toml") as file:
            data = toml.load(file)

        password = data.get("config_password", "")
        self.loglevel = data.get("loglevel", logging.WARNING)
        self.debug = debug
        dsn = f"postgresql://beattie:{password}@localhost/beattie"
        self.db = DatabaseInterface(dsn)
        self.config = Config(self)
        self.uptime = datetime.now().astimezone()
        self.extra = {}
        self.new_logger()
        if debug:
            self.loglevel = logging.DEBUG
            self.archive_task = None
        else:
            self.archive_task = do_every(60 * 60 * 24, self.swap_logs)

    async def close(self) -> None:
        await self.session.close()
        await self.db.close()
        if self.archive_task is not None:
            self.archive_task.cancel()
        await super().close()

    async def swap_logs(self, new: bool = True) -> None:
        if new:
            self.new_logger()
        await asyncio.to_thread(self.archive_logs)

    def new_logger(self) -> None:
        logger = logging.getLogger("discord")
        logger.setLevel(self.loglevel)
        now = datetime.now().astimezone()
        filename = now.strftime("discord%Y%m%d%H%M.log")
        handler = logging.FileHandler(filename=filename, encoding="utf-8", mode="w")
        handler.setFormatter(
            logging.Formatter("%(asctime)s:%(levelname)s:%(name)s: %(message)s")
        )
        logger.addHandler(handler)
        self.logger = logger

    def archive_logs(self) -> None:
        logname = "logs.tar"
        if os.path.exists(logname):
            mode = "a"
        else:
            mode = "w"
        # get all logfiles but newest
        old_logs = sorted(Path(".").glob("*.log"), key=os.path.getmtime)[:-1]
        with tarfile.open(logname, mode) as tar:
            for log in old_logs:
                name = f"{log.name}.xz"
                with open(log, "rb") as r, lzma.open(name, "w") as w:
                    for line in r:
                        w.write(line)
                tar.add(name)
                os.unlink(name)
                log.unlink()

    async def handle_error(self, ctx: Context, e: Exception) -> None:
        if isinstance(e, (commands.CommandInvokeError, commands.ExtensionFailed)):
            e = e.original
        if isinstance(e, commands.MissingRequiredArgument):
            await ctx.send("Missing required arguments.")
        elif isinstance(e, commands.BadArgument):
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
            raise e from None

    async def on_ready(self) -> None:
        assert self.user is not None
        print("Logged in as")
        print(self.user.name)
        print(self.user.id)
        print("------")

    @overload
    async def get_context(self, message: Message) -> BContext:
        ...

    @overload
    async def get_context(self, message: Message, *, cls: Type[C]) -> C:
        ...

    async def get_context(
        self, message: Message, *, cls: Type[Context] = None
    ) -> Context:
        return await super().get_context(message, cls=cls or BContext)

    async def on_command_error(self, ctx: Context, e: Exception) -> None:
        if not hasattr(ctx.command, "on_error"):
            await self.handle_error(ctx, e)

    async def on_error(self, event_method: str, *args: Any, **kwargs: Any) -> None:
        _, e, _ = sys.exc_info()
        if isinstance(e, (commands.CommandInvokeError, commands.ExtensionFailed)):
            e = e.original
        if not isinstance(e, self.general_ignore):
            await super().on_error(event_method, *args, **kwargs)

    def get(self, *args: Any, **kwargs: Any) -> contextmanagers.get:
        return contextmanagers.get(self.session, *args, **kwargs)
