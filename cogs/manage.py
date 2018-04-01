import discord
from discord.ext import commands

from utils.converters import Union

member_or_channel = Union(discord.Member, discord.TextChannel)


class Manage:
    def __init__(self, bot):
        self.config = bot.config

    async def __global_check(self, ctx):
        if await ctx.bot.is_owner(ctx.author) or ctx.guild is None:
            return True
        cog = ctx.command.cog_name
        guild_conf = await self.config.get(ctx.guild.id)
        blacklist = guild_conf.get('cog_blacklist') or ''
        return f'{cog},' not in blacklist

    async def __global_check_once(self, ctx):
        if not ctx.channel.permissions_for(ctx.me).send_messages:
            return False
        if await ctx.bot.is_owner(ctx.author) or ctx.guild is None:
            return True
        guild = ctx.guild
        member_conf = await self.config.get_member(guild.id, ctx.author.id)
        member_plonked = member_conf.get('plonked', False)
        if member_plonked:
            return False
        channel_conf = await self.config.get_channel(guild.id, ctx.channel.id)
        channel_plonked = channel_conf.get('plonked', False)
        return not channel_plonked

    async def __local_check(self, ctx):
        if ctx.guild is None:
            return False
        return (await ctx.bot.is_owner(ctx.author)
                or ctx.channel.permissions_for(ctx.author).manage_guild)

    @commands.command()
    async def enable(self, ctx, cog):
        """Enable a cog in the guild."""
        if ctx.bot.get_cog(cog) is None:
            await ctx.send("That cog doesn't exist.")
            return
        guild_conf = await self.config.get(ctx.guild.id)
        blacklist = guild_conf.get('cog_blacklist') or ''
        if f'{cog},' not in blacklist:
            await ctx.send('Cog is already enabled.')
            return
        blacklist = blacklist.replace(f'{cog},', '')
        await self.config.set(ctx.guild.id, cog_blacklist=blacklist)
        await ctx.send('Cog enabled for this guild.')

    @commands.command()
    async def disable(self, ctx, cog):
        """Disable a cog in the guild."""
        if ctx.bot.get_cog(cog) is None:
            await ctx.send("That cog doesn't exist.")
            return
        guild_conf = await self.config.get(ctx.guild.id)
        blacklist = guild_conf.get('cog_blacklist') or ''
        if f'{cog},' in blacklist:
            await ctx.send('Cog is already disabled.')
            return
        blacklist += f'{cog},'
        await self.config.set(ctx.guild.id, cog_blacklist=blacklist)
        await ctx.send('Cog disabled for this guild.')

    @commands.command()
    async def prefix(self, ctx, prefix=''):
        """Set a custom prefix for this guild. Pass no prefix to reset."""
        await self.config.set(ctx.guild.id, prefix=prefix)
        await ctx.send('Guild prefix set.')

    @commands.command()
    async def plonk(self, ctx, target: member_or_channel):
        """Disallow a member from using commands on this server, or disallow
        commands from being used in a channel."""
        await self._plonker(ctx, target, True)

    @commands.command()
    async def unplonk(self, ctx, target: member_or_channel):
        """Allow a member to use commands on this server, or allow commands
        to be used in a channel."""
        await self._plonker(ctx, target, False)

    @commands.command()
    @commands.bot_has_permissions(manage_messages=True)
    async def clear(self, ctx, num: int):
        """Delete the last num messages from the channel."""
        await ctx.channel.purge(limit=num)

    async def _plonker(self, ctx, target, plonked):
        if isinstance(target, discord.Member):
            type_ = 'Member'
            update = self.config.update_member
        else:
            type_ = 'Channel'
            update = self.config.update_channel
        un = 'un' if not plonked else ''
        await update(ctx.guild.id, target.id, plonked=plonked)
        await ctx.send(f'{type_} {un}plonked.')


def setup(bot):
    bot.add_cog(Manage(bot))
