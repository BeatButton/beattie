import datetime

import discord
import psutil
from discord.ext import commands
from discord.ext.commands import Cog

from bot import BeattieBot
from context import BContext


class Stats(Cog):
    """Bot usage statistics."""

    def __init__(self) -> None:
        self.process = psutil.Process()
        self.process.cpu_percent()

    @commands.command()
    async def uptime(self, ctx: BContext) -> None:
        """Tells you how long the bot has been up for."""
        await ctx.send(f"Uptime: {self.get_bot_uptime(ctx.bot)}")

    @commands.command(aliases=["stats"])
    async def about(self, ctx: BContext) -> None:
        """Tells you information about the bot itself."""

        embed = discord.Embed()

        bot = ctx.bot

        if bot.owner_id is None:
            await bot.is_owner(ctx.author)

        owner_id = bot.owner_id
        assert owner_id is not None
        owner = bot.get_user(owner_id)
        assert owner is not None

        embed.set_author(name=str(owner), icon_url=str(owner.avatar_url))

        total_members = sum(len(s.members) for s in bot.guilds)
        unique_members = len(bot.users)

        voice = 0
        text = 0
        for channel in bot.get_all_channels():
            if isinstance(channel, discord.TextChannel):
                text += 1
            elif isinstance(channel, discord.VoiceChannel):
                voice += 1

        members = f"{total_members} total\n{unique_members} unique"
        embed.add_field(name="Members", value=members)
        embed.add_field(name="Channels", value=f"{text} text\n{voice} voice")
        embed.add_field(name="Uptime", value=self.get_bot_uptime(bot, True))
        embed.set_footer(
            text="Made with discord.py", icon_url="http://i.imgur.com/5BFecvA.png"
        )
        try:
            embed.timestamp = bot.uptime
        except AttributeError:
            pass

        embed.add_field(name="Guilds", value=str(len(bot.guilds)))

        cpu_usage = self.process.cpu_percent()
        memory_usage = self.process.memory_full_info().uss / 2 ** 20
        embed.add_field(name="CPU Usage", value=f"{cpu_usage:.2f}%")
        embed.add_field(name="Memory Usage", value=f"{memory_usage:.2f} MiB")
        await ctx.send(embed=embed)

    def get_bot_uptime(self, bot: BeattieBot, brief: bool = False) -> str:
        now = datetime.datetime.now()
        try:
            delta = now - bot.uptime
        except AttributeError:
            delta = datetime.timedelta()
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        if not brief:
            if days:
                fmt = "{d} days, {h} hours, {m} minutes, and {s} seconds"
            else:
                fmt = "{h} hours, {m} minutes, and {s} seconds"
        else:
            fmt = "{h}h {m}m {s}s"
            if days:
                fmt = "{d}d " + fmt

        return fmt.format(d=days, h=hours, m=minutes, s=seconds)


def setup(bot: BeattieBot) -> None:
    bot.add_cog(Stats())
