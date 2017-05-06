import time

from discord.ext import commands
import yaml

from utils import checks


class Default:
    def __init__(self, bot):
        self.bot = bot
        try:
            with open('config/guilds.yaml') as file:
                self.bot.config = yaml.load(file)
        except FileNotFoundError:
            self.bot.config = {}
        else:
            if self.bot.config is None:
                self.bot.config = {}

    async def __global_check(self, ctx):
        if await self.bot.is_owner(ctx.author):
            return True
        cog = ctx.command.cog_name
        guild_conf = self.bot.config.get(ctx.guild.id, {})
        blacklist = guild_conf.get('cog_blacklist', set())
        return cog not in blacklist

    def _update_config(self):
        with open('config/guilds.yaml', 'w') as file:
            yaml.dump(self.bot.config, file)

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
        guild_conf = self.bot.config.setdefault(ctx.guild.id, {})
        blacklist = guild.conf.get('cog_blacklist', set())
        try:
            blacklist.remove(cog)
        except KeyError:
            await ctx.send('Cog is already enabled.')
        else:
            guild_conf['cog_blacklist'] = blacklist
            await ctx.send('Cog enabled for this guild.')
            self._update_config()

    @commands.command()
    @checks.is_owner_or(manage_guild=True)
    async def disable(self, ctx, cog):
        """Disable a cog in the guild."""
        if self.bot.get_cog(cog) is None:
            await ctx.send("That cog doesn't exist.")
            return
        guild_conf = self.bot.config.setdefault(ctx.guild.id, {})
        blacklist = guild.conf.get('cog_blacklist', set())
        if cog in blacklist:
            await ctx.send('Cog is already disabled.')
            return
        blacklist.add(cog)
        guild_conf['cog_blacklist'] = blacklist
        await ctx.send('Cog disabled for this guild.')
        self._update_config()

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
        guild_conf = self.bot.config.setdefault(ctx.guild.id, {})
        guild_conf['welcome_message'] = message
        self._update_config()
        await ctx.send('Welcome message set.')


def setup(bot):
    bot.add_cog(Default(bot))
