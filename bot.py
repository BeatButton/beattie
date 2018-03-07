import datetime
import inspect
import sys

import aiohttp
from asyncqlio.db import DatabaseInterface
import discord
from discord.ext import commands
import yaml

from config import Config
from context import BContext
from utils import contextmanagers, decorators, exceptions
from utils.etc import default_channel


class BeattieBot(commands.Bot):
    """An extension of Bot. Allow use with self bots and handles errors in an
    ordered way"""
    command_ignore = (commands.CommandNotFound, commands.CheckFailure)
    general_ignore = (ConnectionResetError, )

    def __init__(self, command_prefix='b>', *args, pm_help=None, **kwargs):
        self_bot = kwargs.get('self_bot')
        if self_bot:
            game = None
            status = discord.Status.idle
            pre = command_prefix
        else:
            game = discord.Game(name='b>help')
            status = None

            async def pre(bot, message):
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
                guild_conf = await bot.config.get(message.guild.id)
                guild_pre = guild_conf.get('prefix')
                if not guild_pre:
                    return prefix
                else:
                    return prefix + (guild_pre,)

        super().__init__(pre, *args, **kwargs, game=game, status=status, pm_help=pm_help)
        with open('config/config.yaml') as file:
            data = yaml.load(file)

        password = data.get('config_password', '')
        self.session = aiohttp.ClientSession(loop=self.loop)
        dsn = f'postgresql://beattie:{password}@localhost/beattie'
        self.db = DatabaseInterface(dsn)
        self.loop.create_task(self.db.connect())
        self.config = Config(self)
        self.uptime = datetime.datetime.utcnow()

    def _do_cleanup(self):
        self.session.close()
        self.loop.create_task(self.db.close())
        super()._do_cleanup()

    async def handle_error(self, ctx, e):
        e = getattr(e, 'original', e)
        if isinstance(e, commands.MissingRequiredArgument):
            await ctx.send('Missing required arguments.')
        elif isinstance(e, commands.BadArgument):
            await ctx.send('Bad arguments.')
        elif isinstance(e, exceptions.ResponseError):
            await ctx.send(f'An HTTP request failed with error code {e.code}')
        elif not isinstance(e, self.command_ignore):
            await ctx.send(f'{type(e).__name__}: {e}')
            raise e from None

    async def on_ready(self):
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')
        if not self.user.bot:
            self.owner_id = self.user.id
            afk = True
            status = discord.Status.invisible
            game = None
        else:
            afk = False
            status = discord.Status.online
            game = discord.Game(name='b>help')
        await self.change_presence(activity=game,
                                   status=status,
                                   afk=afk
                                   )

    async def on_message(self, message):
        ctx = await self.get_context(message, cls=BContext)
        if ctx.prefix is not None:
            command = ctx.invoked_with
            if command:
                ctx.command = self.get_command(command.lower())
                await self.invoke(ctx)

    @decorators.bot_only
    async def on_member_join(self, member):
        guild = member.guild
        guild_conf = await self.config.get(guild.id)
        message = guild_conf.get('welcome')
        if message:
            dest = default_channel(guild.me)
            if dest:
                try:
                    message = message.format(mention=member.mention)
                except Exception as e:
                    message = 'Join message broken, please re-set.'
                    raise e from None
                finally:
                    await dest.send(message)

    @decorators.bot_only
    async def on_member_remove(self, member):
        guild = member.guild
        guild_conf = await self.config.get(guild.id)
        message = guild_conf.get('farewell')
        if message:
            dest = default_channel(guild.me)
            if dest:
                try:
                    message = message.format(mention=member.mention)
                except Exception as e:
                    message = 'Leave message broken, please re-set.'
                    raise e from None
                finally:
                    await dest.send(message)

    async def on_command_error(self, ctx, e):
        if not hasattr(ctx.command, 'on_error'):
            await self.handle_error(ctx, e)

    async def on_error(self, event_method, *args, **kwargs):
        _, e, _ = sys.exc_info()
        e = getattr(e, 'original', e)
        if not isinstance(e, self.general_ignore):
            await super().on_error(event_method, *args, **kwargs)

    def get(self, *args, **kwargs):
        return contextmanagers.get(self.session, *args, **kwargs)

    def tmp_dl(self, *args, **kwargs):
        return contextmanagers.tmp_dl(self.session, *args, **kwargs)
