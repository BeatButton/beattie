import time

from discord.ext import commands
import yaml

from utils import checks


class Default:
    def __init__(self, bot):
        self.bot = bot

    async def __global_check(self, ctx):
        if await self.bot.is_owner(ctx.author):
            return True
        cog = ctx.command.cog_name
        guild_conf = await self.bot.config.get(ctx.guild.id, {})
        blacklist = guild_conf.get('cog_blacklist', '')
        return cog not in blacklist

    @commands.command(hidden=True)
    @commands.is_owner()
    async def reload(self, ctx, *, cog):
        cog = cog.lower()
        try:
            self.bot.unload_extension(cog)
            self.bot.load_extension(cog)
        except ModuleNotFoundError:
            await ctx.send('Cog does not exist.')
        else:
            await ctx.send('Reload successful.')

    @commands.command()
    @checks.is_owner_or(manage_guild=True)
    async def enable(self, ctx, cog):
        """Enable a cog in the guild."""
        if self.bot.get_cog(cog) is None:
            await ctx.send("That cog doesn't exist.")
            return
        guild_conf = await self.bot.config.get(ctx.guild.id, {})
        blacklist = guild_conf.get('cog_blacklist')
        if f'{cog},' not in blacklist:
            await ctx.send('Cog is already enabled.')
            return
        blacklist = blacklist.replace(f'{cog},', '')
        guild_conf['cog_blacklist'] = blacklist
        await self.bot.config.set(**guild_conf)
        await ctx.send('Cog enabled for this guild.')

    @commands.command()
    @checks.is_owner_or(manage_guild=True)
    async def disable(self, ctx, cog):
        """Disable a cog in the guild."""
        if self.bot.get_cog(cog) is None:
            await ctx.send("That cog doesn't exist.")
            return
        guild_conf = await self.bot.config.get(ctx.guild.id, {})
        blacklist = guild_conf.get('cog_blacklist', '')
        if f'{cog},' in blacklist:
            await ctx.send('Cog is already disabled.')
            return
        blacklist += f'{cog},'
        guild_conf['cog_blacklist'] = blacklist
        await self.bot.config.set(**guild_conf)
        await ctx.send('Cog disabled for this guild.')

    @commands.command(aliases=['p'])
    async def ping(self, ctx):
        """Get the ping to the websocket."""
        msg = await ctx.send("Pong! :ping_pong:")

        before = time.monotonic()
        await (await self.bot.ws.ping())
        after = time.monotonic()
        ping_time = (after - before) * 1000

        await msg.edit(content=f'{msg.content} **{ping_time:.0f}ms**')

    @commands.command()
    async def source(self, ctx):
        """Get the source for the bot."""
        await ctx.send('https://github.com/BeatButton/beattie-bot')

    @commands.command()
    @checks.is_owner_or(manage_guild=True)
    async def greet(self, ctx, *, message=None):
        """Set the member greeting for this guild. Disables if no message.

        Include a {} in the message where you want to mention the newcomer"""
        await self.bot.config.set(ctx.guild.id, welcome=message)
        await ctx.send('Welcome message set.')

    @commands.command()
    @checks.is_owner_or(manage_guild=True)
    async def leave(self, ctx, *, message=None):
        """Set the member-left message for this guild. Disables if no message.

        Include a {} in the message where you want to mention the deserter"""
        await self.bot.config.set(ctx.guild.id, farewell=message)
        await ctx.send('Leave message set.')


def setup(bot):
    bot.add_cog(Default(bot))
