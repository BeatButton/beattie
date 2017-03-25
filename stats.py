from collections import Counter
import datetime
import logging
import os
import psutil

import discord
from discord.ext import commands

from utils import checks


class Stats:
    """Bot usage statistics."""

    def __init__(self, bot):
        self.bot = bot

    async def on_command(self, ctx):
        self.bot.commands_used[ctx.command.qualified_name] += 1
        message = ctx.message
        destination = None
        if isinstance(message.channel, discord.abc.PrivateChannel):
            destination = 'Private Message'
        else:
            destination = f'#{message.channel.name} ({message.guild.name})'

        self.bot.logger.info(f'{message.created_at}: {message.author.name} in '
                             f'{destination}: {message.content}')

    @commands.command(hidden=True)
    @checks.is_owner()
    async def commandstats(self, ctx):
        p = commands.Paginator()
        counter = self.bot.commands_used
        width = len(max(counter, key=len))
        total = sum(counter.values())

        fmt = '{0:<{width}}: {1}'
        p.add_line(fmt.format('Total', total, width=width))
        for key, count in counter.most_common():
            p.add_line(fmt.format(key, count, width=width))

        for page in p.pages:
            await ctx.send(page)

    @commands.command()
    async def uptime(self, ctx):
        """Tells you how long the bot has been up for."""
        await ctx.send(f'Uptime: {self.get_bot_uptime()}')

    @commands.command(aliases=['stats'])
    async def about(self, ctx):
        """Tells you information about the bot itself."""

        embed = discord.Embed()

        try:
            self.owner
        except AttributeError:
            self.owner = await self.bot.get_user_info(140293604726800385)

        embed.set_author(name=str(self.owner), icon_url=self.owner.avatar_url)

        total_members = sum(len(s.members) for s in self.bot.guilds)
        total_online = sum(1 for m in self.bot.get_all_members()
                           if m.status != discord.Status.offline)
        unique_members = len(self.bot.users)
        unique_online = len(set(member.id for member
                                in self.bot.get_all_members()
                                if member.status == discord.Status.online))
        voice = 0
        text = 0
        for channel in self.bot.get_all_channels():
            if isinstance(channel, discord.TextChannel):
                text += 1
            else:
                voice += 1

        members = (f'{total_members} total\n{total_online} online\n'
                   f'{unique_members} unique\n{unique_online} unique online')
        embed.add_field(name='Members', value=members)
        embed.add_field(name='Channels', value=f'{text + voice} total\n'
                        f'{text} text\n{voice} voice')
        embed.add_field(name='Uptime', value=self.get_bot_uptime(brief=True))
        embed.set_footer(text='Made with discord.py',
                         icon_url='http://i.imgur.com/5BFecvA.png')
        embed.timestamp = self.bot.uptime

        embed.add_field(name='Guilds', value=len(self.bot.guilds))
        embed.add_field(name='Commands Run',
                        value=sum(self.bot.commands_used.values()))

        memory_usage = psutil.Process().memory_full_info().uss / 1024**2
        embed.add_field(name='Memory Usage', value=f'{memory_usage:.2f} MiB')

        await ctx.send(embed=embed)

    def get_bot_uptime(self, *, brief=False):
        now = datetime.datetime.utcnow()
        delta = now - self.bot.uptime
        hours, remainder = divmod(int(delta.total_seconds()), 3600)
        minutes, seconds = divmod(remainder, 60)
        days, hours = divmod(hours, 24)

        if not brief:
            if days:
                fmt = '{d} days, {h} hours, {m} minutes, and {s} seconds'
            else:
                fmt = '{h} hours, {m} minutes, and {s} seconds'
        else:
            fmt = '{h}h {m}m {s}s'
            if days:
                fmt = '{d}d ' + fmt

        return fmt.format(d=days, h=hours, m=minutes, s=seconds)


def setup(bot):
    bot.commands_used = Counter()
    bot.add_cog(Stats(bot))
