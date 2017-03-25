from json import JSONDecodeError
import random
import re

from aiohttp import ClientResponseError
import discord
from discord.ext import commands

from utils import checks


class XKCD:
    def __init__(self, bot):
        self.bot = bot
        with open('data/why.txt', encoding='utf8') as file:
            self.questions = tuple(file.readlines())

    @commands.command()
    async def why(self, ctx):
        """Asks a question."""
        await ctx.send(random.choice(self.questions))

    @commands.group()
    async def xkcd(self, ctx, *, inp=None):
        """Commands for getting xkcd comics"""
        async with ctx.typing():
            url = 'https://xkcd.com/info.0.json'
            async with self.bot.session.get(url) as resp:
                self.xkcd_data = await resp.json()
            if inp == 'random':
                await ctx.invoke(self.random)
            elif inp in ('latest', 'current'):
                await ctx.invoke(self.latest)
            else:
                if inp:
                    await ctx.invoke(self.comic, inp=inp)
                else:
                    await ctx.invoke(self.random)

    @xkcd.command()
    async def random(self, ctx):
        """Gets a random xkcd comic."""
        await ctx.invoke(self.comic,
                         inp=random.randint(1, self.xkcd_data['num']))

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
            match = re.search(r'xkcd\.com/(\d+)/\s', text)
            if match:
                number = int(match.groups()[0])
            else:
                await ctx.send('No comic found.')
                return
        else:
            if number > self.xkcd_data['num']:
                await ctx.send('No comic found.')
                return

        url = f'https://xkcd.com/{number}/info.0.json'
        async with self.bot.session.get(url) as resp:
            try:
                data = await resp.json()
            # JSONDecodeError on Windows and ClientResponseError on Linux
            # aiohttp is not a good library
            except (JSONDecodeError, ClientResponseError):
                data = {'title': '404',
                        'img': 'http://www.explainxkcd.com/wiki/'
                               'images/9/92/not_found.png',
                        'alt': 'Comic not found.',
                        'num': 404,
                        }
        await ctx.send(embed=format_comic(data))

    @commands.command(hidden=True)
    async def sudo(self, ctx, *, inp):
        if checks.is_owner_check(ctx):
            await ctx.send('Operation successful.')
        else:
            await ctx.send('Unable to lock /var/lib/dpkg/, are you root?')


def format_comic(data):
    embed = discord.Embed()
    embed.title = data['title']
    embed.set_image(url=data['img'])
    embed.set_footer(text=data['alt'])
    embed.url = f"https://www.xkcd.com/{data['num']}/"
    return embed


def setup(bot):
    bot.add_cog(XKCD(bot))
