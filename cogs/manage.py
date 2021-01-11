from discord import Member, Message, TextChannel
from discord.ext import commands
from discord.ext.commands import Cog

from bot import BeattieBot
from context import BContext


class Manage(Cog):
    def __init__(self, bot: BeattieBot) -> None:
        self.config = bot.config

    async def bot_check(self, ctx: BContext) -> bool:
        if await ctx.bot.is_owner(ctx.author):
            return True
        guild = ctx.guild
        if guild is None:
            return True
        cog = ctx.command.cog_name
        guild_conf = await self.config.get_guild(guild.id)
        blacklist = guild_conf.get("cog_blacklist") or ""
        return f"{cog}," not in blacklist

    async def bot_check_once(self, ctx: BContext) -> bool:
        guild = ctx.guild
        if guild is None:
            return True
        me = ctx.me
        channel = ctx.channel
        assert isinstance(me, Member)
        assert isinstance(channel, TextChannel)
        return channel.permissions_for(me).send_messages

    async def cog_check(self, ctx: BContext) -> bool:
        if ctx.guild is None:
            return False
        author = ctx.author
        channel = ctx.channel
        assert isinstance(author, Member)
        assert isinstance(channel, TextChannel)
        return (
            await ctx.bot.is_owner(author)
            or channel.permissions_for(author).manage_guild
        )

    @commands.command()
    async def enable(self, ctx: BContext, cog: str) -> None:
        """Enable a cog in the guild."""
        if ctx.bot.get_cog(cog) is None:
            await ctx.send("That cog doesn't exist.")
            return
        guild = ctx.guild
        assert guild is not None
        guild_conf = await self.config.get_guild(guild.id)
        blacklist = guild_conf.get("cog_blacklist") or ""
        if f"{cog}," not in blacklist:
            await ctx.send("Cog is already enabled.")
            return
        blacklist = blacklist.replace(f"{cog},", "")
        await self.config.set_guild(guild.id, cog_blacklist=blacklist)
        await ctx.send("Cog enabled for this guild.")

    @commands.command()
    async def disable(self, ctx: BContext, cog: str) -> None:
        """Disable a cog in the guild."""
        if ctx.bot.get_cog(cog) is None:
            await ctx.send("That cog doesn't exist.")
            return
        guild = ctx.guild
        assert guild is not None
        guild_conf = await self.config.get_guild(guild.id)
        blacklist = guild_conf.get("cog_blacklist") or ""
        if f"{cog}," in blacklist:
            await ctx.send("Cog is already disabled.")
            return
        blacklist += f"{cog},"
        await self.config.set_guild(guild.id, cog_blacklist=blacklist)
        await ctx.send("Cog disabled for this guild.")

    @commands.command()
    async def prefix(self, ctx: BContext, prefix: str = "") -> None:
        """Set a custom prefix for this guild. Pass no prefix to reset."""
        guild = ctx.guild
        assert guild is not None
        await self.config.set_guild(guild.id, prefix=prefix)
        await ctx.send("Guild prefix set.")

    @commands.command()
    @commands.bot_has_permissions(manage_messages=True)
    async def purge(self, ctx: BContext, until: Message) -> None:
        """Delete messages since the specified message id."""
        channel = ctx.channel
        assert isinstance(channel, TextChannel)
        await channel.purge(before=ctx.message, after=until)
        await ctx.message.add_reaction("<:blobuwu:337437098036690944>")

    @commands.command()
    @commands.bot_has_permissions(manage_messages=True)
    async def clean(self, ctx: BContext, until: Message) -> None:
        """Delete messages from the bot since the specified message id."""
        channel = ctx.channel
        assert isinstance(channel, TextChannel)
        await channel.purge(
            before=ctx.message, after=until, check=lambda msg: msg.author == ctx.me
        )
        await ctx.message.add_reaction("<:blobuwu:337437098036690944>")


def setup(bot: BeattieBot) -> None:
    bot.add_cog(Manage(bot))
