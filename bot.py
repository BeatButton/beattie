import datetime
import os

import aiohttp
import discord
from discord.ext import commands
import yaml

from utils import contextmanagers


class BContext(commands.Context):
    async def reply(self, content, sep='\n'):
        if self.me.bot:
            content = f'{self.author.mention}{sep}{content}'
        return await self.send(content)

    async def send(self, content=None, *, embed=None, **kwargs):
        if self.me.bot:
            if content is not None and len(str(content)) >= 2000:
                if not os.path.isdir('tmp'):
                    os.makedir('tmp')
                filename = f'tmp/{self.message.id}.txt'
                with open(filename, 'w') as file:
                    file.write(content)
                msg = await self.send('Message too long, see attached file.',
                                      file=filename)
                os.remove(filename)
                return msg
            else:
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
        with open('data/openbrackets.txt', encoding='utf8') as file:
            open_ = file.read()
        with open('data/closebrackets.txt', encoding='utf8') as file:
            close = file.read()
        self.brackets = open_
        self.charmap = str.maketrans(dict(zip(open_, close)))

    def __del__(self):
        self.session.close()

    async def handle_error(self, e, ctx):
        e = getattr(e, 'original', e)
        if isinstance(e, commands.MissingRequiredArgument):
            await ctx.send('Missing required arguments.')
        elif isinstance(e, commands.BadArgument):
            await ctx.send('Bad arguments.')
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
            ctx.command = self.get_command(ctx.invoked_with.lower())
            await self.invoke(ctx)
        elif ctx.author != ctx.me:
            content = message.content
            count = sum(content.count(char) for char in self.brackets)
            if count > len(content) // 2:
                message = ''.join(ch for ch in content if ch in self.brackets)
                await ctx.send(message.translate(self.charmap)[::-1])

    async def on_command_error(self, e, ctx):
        if not hasattr(ctx.command, 'on_error'):
            await self.handle_error(e, ctx)
