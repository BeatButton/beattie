import datetime
import inspect
import io
import sys

import aiohttp
from asyncqlio.db import DatabaseInterface
import discord
from discord.ext import commands

from config import Config
from utils import contextmanagers, decorators, exceptions
import yaml


class BContext(commands.Context):
    """An extension of Context to add reply and mention methods,
    as well as support use with self bots"""
    async def reply(self, content, sep=',\n'):
        if self.me.bot and not isinstance(self.channel, discord.DMChannel):
            content = f'{self.author.display_name}{sep}{content}'
        return await self.send(content)

    async def mention(self, content, sep=',\n'):
        if self.me.bot and not isinstance(self.channel, discord.DMChannel):
            content = f'{self.author.mention}{sep}{content}'
        return await self.send(content)

    async def send(self, content=None, *, embed=None, **kwargs):
        str_content = str(content)
        if len(str_content) > 2000:
            fp = io.StringIO()
            fp.write(str_content)
            fp.seek(0)
            content = None
            file = discord.File(fp, filename=f'{self.message.id}.txt')
            if kwargs['files'] is not None:
                kwargs['files'].append(file)
            else:
                kwargs['file'] = file
        if self.me.bot:
            return await super().send(content, embed=embed, **kwargs)
        else:
            if content is not None:
                content = f'{self.message.content}\n{content}'
            await self.message.edit(content=content, embed=embed)
            if kwargs:
                return await super().send(**kwargs)
            return self.message

    def typing(self):
        if self.me.bot:
            return super().typing()
        else:
            return contextmanagers.null()


class BeattieBot(commands.Bot):
    """An extension of Bot. Allow use with self bots and handles errors in an
    ordered way"""
    command_ignore = (commands.CommandNotFound, commands.CheckFailure)
    general_ignore = (ConnectionResetError, )

    def __init__(self, command_prefix='b>', *args, **kwargs):
        self_bot = kwargs.get('self_bot')
        if self_bot:
            game = None
            status = discord.Status.idle
            pre = command_prefix
        else:
            game = discord.Game(name='b>help')
            status = None

            async def pre(self, message):
                prefix = command_prefix
                if callable(prefix):
                    prefix = prefix(self, message)
                if inspect.isawaitable(prefix):
                    prefix = await prefix
                if isinstance(prefix, str):
                    prefix = (prefix,)
                elif isinstance(prefix, list):
                    prefix = tuple(prefix)
                if message.guild is None:
                    return prefix
                guild_conf = await self.config.get(message.guild.id)
                guild_pre = guild_conf.get('prefix')
                if not guild_pre:
                    return prefix
                else:
                    return prefix + (guild_pre,)

        super().__init__(pre, *args, **kwargs, game=game, status=status)
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
            await self.change_presence(afk=True)

    async def on_message(self, message):
        ctx = await self.get_context(message, cls=BContext)
        if ctx.prefix is not None:
            command = ctx.invoked_with
            if command:
                ctx.command = self.get_command(command.lower())
                await self.invoke(ctx)

    @decorators.bot_only
    async def on_guild_join(self, guild):
        bots = sum(m.bot for m in guild.members)
        if bots > 10 and bots / len(guild.members) > 0.5:
            try:
                dest = guild.default_channel
                await dest.send("This gulid's bot to user ratio is too high.")
            except discord.Forbidden:
                pass
            finally:
                await guild.leave()

    @decorators.bot_only
    async def on_guild_remove(self, guild):
        await self.config.remove(guild.id)

    @decorators.bot_only
    async def on_member_join(self, member):
        guild = member.guild
        guild_conf = await self.config.get(guild.id)
        message = guild_conf.get('welcome')
        if message:
            await guild.default_channel.send(message.format(member.mention))

    @decorators.bot_only
    async def on_member_remove(self, member):
        guild = member.guild
        guild_conf = await self.config.get(guild.id)
        message = guild_conf.get('farewell')
        if message:
            await guild.default_channel.send(message.format(member.mention))

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
