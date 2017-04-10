import datetime

import aiohttp
import discord
from discord.ext import commands

from utils import contextmanagers, exceptions


class BContext(commands.Context):
    async def reply(self, content, sep='\n'):
        if self.me.bot:
            content = f'{self.author.display_name}{sep}{content}'
        return await self.send(content)

    async def mention(self, content, sep='\n'):
        if self.me.bot:
            content = f'{self.author.mention}{sep}{content}'
        return await self.send(content)

    async def send(self, content=None, *, embed=None, **kwargs):
        if self.me.bot:
            return await super().send(content, embed=embed, **kwargs)
        elif content is not None:
            content = f'{self.message.content}\n{content}'
            await self.message.edit(content=content)
            return self.message
        elif embed is not None:
            await self.message.delete()
            return await super().send(embed=embed, **kwargs)

    def typing(self):
        if self.me.bot:
            return super().typing()
        else:
            return contextmanagers.null()


class BeattieBot(commands.Bot):
    ignore = (commands.CommandNotFound, commands.CheckFailure)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.session = aiohttp.ClientSession(loop=self.loop)

    def __del__(self):
        self.session.close()
        try:
            delete = super().__del__
        except AttributeError:
            pass
        else:
            delete()

    async def is_owner(self, member):
        if self.user.bot:
            return await super().is_owner(member)
        else:
            return True

    async def handle_error(self, e, ctx):
        e = getattr(e, 'original', e)
        if isinstance(e, commands.MissingRequiredArgument):
            await ctx.send('Missing required arguments.')
        elif isinstance(e, commands.BadArgument):
            await ctx.send('Bad arguments.')
        elif isinstance(e, exceptions.ResponseError):
            await ctx.send(f'An HTTP request failled with error code {e.code}')
        elif not isinstance(e, self.ignore):
            await ctx.send(f'{type(e).__name__}: {e}')
            raise e

    async def on_ready(self):
        print('Logged in as')
        print(self.user.name)
        print(self.user.id)
        print('------')
        if not hasattr(self, 'uptime'):
            self.uptime = datetime.datetime.utcnow()

    async def on_message(self, message):
        ctx = await self.get_context(message, cls=BContext)
        if ctx.prefix is not None:
            command = ctx.invoked_with
            if command:
                ctx.command = self.get_command(command.lower())
                await self.invoke(ctx)

    async def on_command_error(self, e, ctx):
        if not hasattr(ctx.command, 'on_error'):
            await self.handle_error(e, ctx)

    def get(self, *args, **kwargs):
        return contextmanagers.get(self.session, *args, **kwargs)
