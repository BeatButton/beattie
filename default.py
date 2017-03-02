from codecs import encode
import random

from discord.ext import commands
from lxml import etree

from utils import checks


class Default:
    def __init__(self, bot):
        self.bot = bot
        with open('data/why.txt') as file:
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
    async def why(self, ctx):
        """Asks a question."""
        await ctx.send(random.choice(self.questions))

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

    @commands.command(hidden=True, aliases=['gel'])
    async def gelbooru(self, ctx, *tags):
        async with ctx.typing():
            entries = []
            url = 'http://gelbooru.com/index.php'
            params = {'page': 'dapi',
                      's': 'post',
                      'q': 'index',
                      'tags': '+'.join(tags)}
            async with self.bot.session.get(url, params=params) as resp:
                root = etree.fromstring((await resp.text()).encode(),
                                        etree.HTMLParser())
            search_nodes = root.findall(".//post")
            for node in search_nodes:
                image = dict(node.items()).get('file_url', None)
                if image:
                    entries.append(image)
            try:
                message = f'http:{random.choice(entries)}'
            except IndexError:
                message = 'No images found.'
        await ctx.send(message)

    @commands.command(hidden=True)
    async def massage(self, ctx):
        await ctx.invoke(self.gelbooru, 'massage')

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


def setup(bot):
    bot.add_cog(Default(bot))
