from discord import File
from discord.ext import commands


class Default:
    """Default useful commands."""
    @commands.command(aliases=['p'])
    async def ping(self, ctx):
        """Get the ping to the websocket."""
        await ctx.send(f'Pong! :ping_pong: **{ctx.bot.latency*1000:.0f}ms**')

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
        """thanks"""
        await ctx.send(':purple_heart:')

    @commands.command(hidden=True)
    async def confetti(self, ctx, num: int=1):
        """Throw some confetti."""
        if num > 200:
            await ctx.send("I don't have that much confetti "
                           '<:blobpensive:337436989676716033>')
        elif num < 1:
            await ctx.send('<:blobthinkingdown:337436994353365002>')
        else:
            await ctx.send('\U0001f389' * num)

    @commands.command(hidden=True)
    async def doubt(self, ctx):
        """doubt"""
        await ctx.send(file=File('data/doubt.jpg'))

    @commands.command(hidden=True)
    async def mystery(selfself, ctx):
        """???"""
        await ctx.send(file=File('data/mystery.webm'))


def setup(bot):
    bot.add_cog(Default())
