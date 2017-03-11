from codecs import encode
import json
import random
import re

import discord
from discord.ext import commands
from lxml import etree

from utils import checks


class Default:
    def __init__(self, bot):
        self.bot = bot
        with open('data/why.txt', encoding='utf8') as file:
            self.questions = tuple(file.readlines())

    @commands.command(aliases=['p'])
    async def ping(self, ctx):
        """Pong.

        Responds to the ping with "pong."
        """
        msg = await ctx.send('pong')
        delta = (msg.created_at - ctx.message.created_at).total_seconds()
        await msg.edit(content=f'{msg.content}\nTime to respond: '
                       f'{delta:.3f} seconds')

    @commands.command()
    async def choose(self, ctx, *options):
        """Choose between some options. Use quotes if they have spaces."""
        await ctx.send(random.choice(options))

    @commands.command()
    async def why(self, ctx):
        """Asks a question."""
        await ctx.send(random.choice(self.questions))

    @commands.group()
    async def xkcd(self, ctx, *, inp=''):
        """Commands for getting xkcd comics"""
        async with ctx.typing():
            url = 'https://xkcd.com/info.0.json'
            async with self.bot.session.get(url) as resp:
                self.xkcd_data = json.loads(await resp.text())
            if inp == 'random':
                await ctx.invoke(self.random)
            elif inp in ('latest', 'current'):
                await ctx.invoke(self.latest)
            else:
                if inp == '':
                    await ctx.invoke(self.random)
                else:
                    await ctx.invoke(self.comic, inp=inp)

    @xkcd.command()
    async def random(self, ctx):
        """Gets a random xkcd comic."""
        number = random.randint(1, self.xkcd_data['num'])
        url = f'https://xkcd.com/{number}/info.0.json'
        async with self.bot.session.get(url) as resp:
            data = json.loads(await resp.text())
        await ctx.send(embed=format_comic(data))

    @xkcd.command()
    async def latest(self, ctx):
        """Gets the latest xkcd comic."""
        await ctx.send(embed=format_comic(self.xkcd_data))

    @xkcd.command()
    async def comic(self, ctx, *, inp):
        """Gets an xkcd comic by number or content."""
        try:
            number = int(inp)
        except ValueError:
            url = 'https://duckduckgo.com/html/'
            params = {'q': f'{inp} xkcd'}
            async with self.bot.session.get(url, params=params) as resp:
                text = await resp.text()
            match = re.search(r'xkcd.com/(\d+)', text)
            if match:
                number = match.groups()[0]
            else:
                await ctx.send('No comic found.')

        url = f'https://xkcd.com/{number}/info.0.json'
        async with self.bot.session.get(url) as resp:
            data = json.loads(await resp.text())
        await ctx.send(embed=format_comic(data))

    @commands.group(aliases=['str', 's'])
    async def string(self, ctx):
        """Commands for doing stuff to strings."""
        if ctx.invoked_subcommand is None:
            await ctx.send('Invalid command passed. '
                           f'Try "{ctx.prefix}help string"')

    @string.command(aliases=['rev', 'r'])
    async def reverse(self, ctx, *, inp):
        """Reverse a string."""
        await ctx.send(inp[::-1])

    @string.command(aliases=['rot'])
    async def rot13(self, ctx, *, inp):
        """Apply rot13 to a string.

        Uses the shift cipher with key 13."""
        await ctx.send(encode(inp, 'rot_13'))

    @commands.command(hidden=True)
    @checks.is_owner()
    async def sudo(self, ctx, *, inp):
        await ctx.send('Operation successful.')

    @sudo.error
    async def sudo_error(self, exception, ctx):
        if isinstance(exception, commands.errors.CheckFailure):
            await ctx.send('Unable to lock /var/lib/dpkg/, are you root?')
        else:
            await self.bot.handle_error(exception, ctx)


def format_comic(data):
    embed = discord.Embed()
    embed.title = data['title']
    embed.set_image(url=data['img'])
    embed.set_footer(text=data['alt'])
    embed.url = f"https://www.xkcd.com/{data['num']}"
    return embed


def setup(bot):
    bot.add_cog(Default(bot))
