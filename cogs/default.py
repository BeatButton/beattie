import time

from discord.ext import commands


class Default:
    @commands.command(aliases=['p'])
    async def ping(self, ctx):
        """Get the ping to the websocket."""
        msg = await ctx.send("Pong! :ping_pong:")

        before = time.monotonic()
        await (await ctx.bot.ws.ping())
        after = time.monotonic()
        ping_time = (after - before) * 1000

        await msg.edit(content=f'{msg.content} **{ping_time:.0f}ms**')

    @commands.command()
    async def source(self, ctx):
        """Get the source for the bot."""
        await ctx.send('https://github.com/BeatButton/beattie')

    @commands.command()
    async def invite(self, ctx):
        """Get the invite for the bot."""
        url = 'https://discordapp.com/oauth2/authorize?client_id={}&scope=bot'
        await ctx.send(url.format(ctx.me.id))

    @commands.command(hidden=True, aliases=['thank', 'thx'])
    async def thanks(self, ctx):
        await ctx.send('no u')


def setup(bot):
    bot.add_cog(Default())
