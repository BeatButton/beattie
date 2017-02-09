from codecs import encode
import os
import random

from discord.ext import commands
from lxml import etree
import requests

from utils import checks


class Default:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['p'])
    async def ping(self, ctx):
        """Pong.

        Responds to the ping with "pong." This is just to let you know the bot's working.
        """
        msg = await ctx.send('pong')
        delta = (msg.created_at - ctx.message.created_at).total_seconds()
        await msg.edit(content=f'{msg.content}\nTime to respond: {delta:.3f} seconds')

    @commands.group(aliases=['str', 's'])
    async def string(self, ctx):
        """Commands for doing stuff to strings."""
        if ctx.invoked_subcommand is None:
            await ctx.send(f'Invalid command passed. Try "{ctx.prefix}help string"')

    @string.command(aliases=['rev', 'r'])
    async def reverse(self, ctx, *, inp):
        """Reverse a string."""
        await ctx.send(inp[::-1])

    @string.command(aliases=['rot'])
    async def rot13(self, ctx, *, inp):
        """Apply rot13 to a string.

        Uses the shift cipher with key 13."""
        await ctx.send(encode(inp, 'rot_13'))

    @commands.command(hidden=True, aliases=['gel'])
    async def gelbooru(self, ctx, *, inp):
        entries = []
        url = 'http://gelbooru.com/index.php?page=dapi&s=post&q=index&tags={}'
        resp = requests.get(url.format('+'.join(inp.strip().split())))
        root = etree.fromstring(resp.content, etree.HTMLParser())
        search_nodes = root.findall(".//post")
        for node in search_nodes:
            image = dict(node.items()).get('file_url', None)
            if image:
                 entries.append(image)
        try:
            message = random.choice(entries)
        except IndexError:
            message = 'No images found.'
        await ctx.send(f'http:{message}')

    @commands.command(name='eval')
    @checks.is_owner()
    async def eval_(self, ctx, *, inp):
        """Uses eval on an expression. Owner only."""
        inp = inp.strip()
        while inp.startswith('`'):
            inp = inp[1:]
        inp = inp.strip()
        if inp.startswith('py'):
            inp = inp[2:]
        while inp.endswith('`'):
            inp = inp[:-1]
        inp.strip()
        import math, cmath, asyncio, discord, aiohttp
        try:
            result = eval(inp)
        except Exception as e:
            result = e
        finally:
            del math, cmath, asyncio, discord, aiohttp
        await ctx.send(f'```py\n{result}```')


def setup(bot):
    bot.add_cog(Default(bot))
