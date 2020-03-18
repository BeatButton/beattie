import inspect
import logging
import lzma
import os
import sys
import tarfile
from datetime import datetime
from pathlib import Path

import aiohttp
import discord
import toml
from asyncqlio.db import DatabaseInterface
from discord.ext import commands
from discord.ext.commands import Bot

from config import Config
from context import BContext
from utils import contextmanagers, exceptions
from utils.aioutils import do_every


class BeattieBot(Bot):
    """A very cute robot boy"""

    command_ignore = (commands.CommandNotFound, commands.CheckFailure)
    general_ignore = (ConnectionResetError,)

    def __init__(self, command_prefix, *args, debug=False, **kwargs):
        async def prefix_func(bot, message):
            prefix = command_prefix
            if callable(prefix):
                prefix = prefix(bot, message)
            if inspect.isawaitable(prefix):
                prefix = await prefix
            if isinstance(prefix, str):
                prefix = (prefix,)
            elif isinstance(prefix, list):
                prefix = tuple(prefix)
            if message.guild is None:
                return prefix
            guild_conf = await bot.config.get_guild(message.guild.id)
            guild_pre = guild_conf.get("prefix")
            if guild_pre:
                prefix = prefix + (guild_pre,)
            return prefix

        help_command = commands.DefaultHelpCommand(dm_help=None)

        super().__init__(
            prefix_func,
            *args,
            **kwargs,
            case_insensitive=True,
            help_command=help_command,
        )
        with open("config/config.toml") as file:
            data = toml.load(file)

        password = data.get("config_password", "")
        self.loglevel = data.get("loglevel", "WARNING")
        self.debug = debug
        self.session = aiohttp.ClientSession(loop=self.loop)
        dsn = f"postgresql://beattie:{password}@localhost/beattie"
        self.db = DatabaseInterface(dsn)
        self.loop.create_task(self.db.connect())
        self.config = Config(self)
        self.uptime = datetime.utcnow()
        if not self.debug:
            self.archive_task = do_every(60 * 60 * 24, self.swap_logs)

    async def close(self):
        await self.session.close()
        await self.db.close()
        self.archive_task.cancel()
        await super().close()

    async def swap_logs(self, new=True):
        if new:
            self.new_logger()
        await self.loop.run_in_executor(None, self.archive_logs)

    def new_logger(self):
        logger = logging.getLogger("discord")
        loglevel = getattr(logging, self.loglevel, logging.CRITICAL)
        logger.setLevel(loglevel)
        now = datetime.utcnow()
        filename = now.strftime("discord%Y%m%d%H%M.log")
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

    async def handle_error(self, ctx, e):
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
            self.logger.exception(message, exc_info=e.__traceback__)
            raise e from None

    async def on_ready(self):
        print("Logged in as")
        print(self.user.name)
        print(self.user.id)
        print("------")
        game = discord.Game(name="b>help")
        await self.change_presence(activity=game)

    async def get_context(self, message, *, cls=None):
        return await super().get_context(message, cls=cls or BContext)

    async def on_command_error(self, ctx, e):
        if not hasattr(ctx.command, "on_error"):
            await self.handle_error(ctx, e)

    async def on_error(self, event_method, *args, **kwargs):
        _, e, _ = sys.exc_info()
        if isinstance(e, (commands.CommandInvokeError, commands.ExtensionFailed)):
            e = e.original
        if not isinstance(e, self.general_ignore):
            await super().on_error(event_method, *args, **kwargs)

    def get(self, *args, **kwargs):
        return contextmanagers.get(self.session, *args, **kwargs)
