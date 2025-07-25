from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

import psutil

import discord
from discord.ext import commands
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext


class Stats(Cog):
    """Bot usage statistics."""

    def __init__(self):
        self.process = psutil.Process()
        self.process.cpu_percent()

    @commands.command()
    async def uptime(self, ctx: BContext):
        """Tells you how long the bot has been up for."""
        await ctx.send(f"Uptime: {self.get_bot_uptime(ctx.bot)}")

    @commands.command(aliases=["stats"])
    async def about(self, ctx: BContext):
        """Tells you information about the bot itself."""

        embed = discord.Embed()

        bot = ctx.bot

        if bot.owner_id is None:
            await bot.is_owner(ctx.author)

        owner = None
        if owner_id := bot.owner_id:
            owner = bot.get_user(owner_id)
        elif owner_ids := bot.owner_ids:
            owner = bot.get_user(next(iter(owner_ids)))

        if owner is not None:
            embed.set_author(
                name=f"Created by {owner}",
                icon_url=owner.display_avatar.url,
            )

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
        embed.add_field(name="Uptime", value=self.get_bot_uptime(bot, brief=True))
        embed.set_footer(
            text="Made with discord.py",
            icon_url="http://i.imgur.com/5BFecvA.png",
        )
        try:
            embed.timestamp = bot.uptime
        except AttributeError:
            pass

        embed.add_field(name="Guilds", value=str(len(bot.guilds)))

        cpu_usage = self.process.cpu_percent()
        memory_usage = self.process.memory_full_info().uss / 2**20
        embed.add_field(name="CPU Usage", value=f"{cpu_usage:.2f}%")
        embed.add_field(name="Memory Usage", value=f"{memory_usage:.2f} MiB")
        await ctx.send(embed=embed)

    def get_bot_uptime(self, bot: BeattieBot, *, brief: bool = False) -> str:
        now = datetime.datetime.now().astimezone()
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


async def setup(bot: BeattieBot):
    await bot.add_cog(Stats())
