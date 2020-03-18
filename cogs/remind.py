import asyncio
from collections import namedtuple
from datetime import datetime

from discord import TextChannel
from discord.ext import commands
from discord.ext.commands import Cog

from schema.remind import Reminder, Table
from utils.checks import is_owner_or
from utils.converters import Time
from utils.etc import reverse_insort


class Remind(Cog):
    def __init__(self, bot):
        self.queue = []
        self.loop = bot.loop
        self.db = bot.db
        self.bot = bot
        self.db.bind_tables(Table)
        self.timer = self.loop.create_task(asyncio.sleep(0))
        self.loop.create_task(self.__init())

    def cog_unload(self):
        self.timer.cancel()

    async def __init(self):
        await self.bot.wait_until_ready()
        await Reminder.create(if_not_exists=True)
        async with self.db.get_session() as s:
            query = s.select(Reminder).order_by(Reminder.time, sort_order="desc")
            self.queue = [reminder async for reminder in await query.all()]
        await self.start_timer()

    @commands.group(invoke_without_command=True)
    async def remind(self, ctx, time: Time, *, topic: commands.clean_content = None):
        """Commands for setting and managing reminders."""
        await self.set_reminder(ctx, time, topic=topic)

    @remind.command(aliases=["set"])
    async def set_reminder(
        self, ctx, time: Time, *, topic: commands.clean_content = None
    ):
        """Have the bot remind you about something.
           First put time (in quotes if there are spaces), then topic"""
        await self.schedule_reminder(ctx, time, topic)
        await ctx.send("Okay, I'll remind you.")

    @set_reminder.error
    async def remind_error(self, ctx, e):
        if isinstance(e, commands.BadArgument, commands.ConversionError):
            await ctx.send(
                "Bad input. Valid input examples:\n"
                "remind 10m pizza\n"
                'remind "two days" check progress'
            )
        else:
            await ctx.bot.handle_error(ctx, e)

    @remind.command(aliases=["channel"])
    @is_owner_or(manage_guild=True)
    async def set_channel(self, ctx, channel: TextChannel = None):
        """Set the channel reminders will appear in. Invoke with no input to reset."""
        await ctx.bot.config.set_guild(
            ctx.guild.id, reminder_channel=channel and channel.id
        )
        if channel is None:
            destination = "the channel they were invoked in"
        else:
            destination = channel.mention
        await ctx.send(f"All reminders will be sent to {destination} from now on.")

    async def schedule_reminder(self, ctx, time, topic):
        async with self.db.get_session() as s:
            reminder = await s.add(
                Reminder(
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    user_id=ctx.author.id,
                    time=time,
                    topic=topic,
                )
            )
        if not self.queue or reminder.time < self.queue[-1].time:
            self.queue.append(reminder)
            self.timer.cancel()
            await self.start_timer()
        else:
            reverse_insort_by_key(
                self.queue, reminder, key=lambda r: r.time, hi=len(self.queue) - 1
            )

    async def send_reminder(self, reminder):
        if (guild := self.bot.get_guild(reminder.guild_id)) and (
            member := guild.get_member(reminder.user_id)
        ):
            guild_conf = await self.bot.config.get_guild(guild.id)
            if channel := guild.get_channel(
                guild_conf.get("reminder_channel") or reminder.channel_id
            ):
                topic = reminder.topic or "something"
                message = f"{member.mention}\nYou asked to be reminded about {topic}."
                await channel.send(message)
        async with self.db.get_session() as s:
            query = s.select(Reminder).where(Reminder.id == reminder.id)
            reminder = await query.first()
            await s.remove(reminder)

    async def start_timer(self):
        self.timer = self.loop.create_task(self.sleep())

    async def sleep(self):
        while self.queue:
            delta = (self.queue[-1].time - datetime.now()).total_seconds()
            if delta <= 0:
                await self.send_reminder(self.queue.pop())
            else:
                await asyncio.sleep(min(delta, 3_000_000))


def setup(bot):
    bot.add_cog(Remind(bot))
