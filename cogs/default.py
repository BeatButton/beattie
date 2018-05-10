from discord import File, Member
from discord.ext import commands


class Default:
    """Default useful commands."""
    @commands.command()
    async def avatar(self, ctx, member: Member = None):
        if member is None:
            member = ctx.author
        await ctx.send(member.avatar_url_as(format='png'))

    @avatar.error
    async def avatar_error(self, ctx, exc):
        if isinstance(exc, commands.BadArgument):
            await ctx.send('Member not found.')
        else:
            await ctx.bot.handle_error(ctx, exc)
    
    @commands.command()
    async def latency(self, ctx):
        """Get the latency to the websocket."""
        await ctx.send(f'WS latency: **{ctx.bot.latency*1000:.0f}ms**')

    @commands.command()
    async def ping(self, ctx):
        """Get how fast the bot reacts to a command message"""
        msg = await ctx.send('...')
        delta = msg.created_at - ctx.message.created_at
        await msg.edit(content=f':ping_pong: **{delta.total_seconds()*1000:.0f}ms**')
        msg = await ctx.channel.get_message(msg.id)
        delta2 = msg.edited_at - ctx.message.created_at
        await msg.edit(content=f'{msg.content}\n**{delta2.total_seconds()*1000:.0f}ms**')

    @commands.command()
    async def source(self, ctx):
        """Get the source for the bot."""
        await ctx.send('https://github.com/BeatButton/beattie')

    @commands.command()
    async def invite(self, ctx):
        """Get the invite for the bot."""
        url = '<https://discordapp.com/oauth2/authorize?client_id={}&scope=bot>'
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
