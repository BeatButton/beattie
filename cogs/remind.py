import asyncio
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional, Union

import discord
from asyncqlio.db import DatabaseInterface
from dateutil import rrule
from discord import AllowedMentions, Embed, TextChannel
from discord.ext import commands, menus
from discord.ext.commands import Cog
from discord.ext.menus import MenuKeysetPages, PageDirection, PageSpecifier
from recurrent.event_parser import RecurringEvent

from bot import BeattieBot
from context import BContext
from schema.remind import Recurring, Reminder, Table
from utils.checks import is_owner_or
from utils.converters import Time
from utils.etc import display_timedelta, reverse_insort_by_key

MINIMUM_RECURRING_DELTA = timedelta(minutes=10)


class ReminderSource(menus.KeysetPageSource):
    def __init__(self, db: DatabaseInterface, user_id: int, guild_id: int):
        self.db = db
        self.user_id = user_id
        self.guild_id = guild_id

    def is_paginating(self) -> bool:
        return True

    async def get_page(self, specifier: PageSpecifier) -> list[Reminder]:
        async with self.db.get_session() as s:
            query = (
                s.select(Reminder)
                .where(
                    (Reminder.user_id == self.user_id)
                    & (Reminder.guild_id == self.guild_id)
                )
                .limit(10)
            )

            if specifier.reference is not None:
                if specifier.direction is PageDirection.after:
                    query = query.where(Reminder.id > specifier.reference[-1]["id"])
                else:
                    query = query.where(Reminder.id < specifier.reference[0]["id"])

            sort_order = "asc" if specifier.direction is PageDirection.after else "desc"
            query = query.order_by(Reminder.id, sort_order=sort_order)

            results = [reminder async for reminder in await query.all()]

        if not results:
            raise ValueError
        if specifier.direction is PageDirection.before:
            results.reverse()

        return results

    async def format_page(self, _: Any, page: Iterable[Reminder]) -> Embed:
        return Embed(
            description="\n".join(
                f'ID {row.id}: "{row.topic}" at {row.time}' for row in page
            )
        )


class Remind(Cog):
    def __init__(self, bot: BeattieBot):
        self.queue: list[Reminder] = []
        self.loop = bot.loop
        self.db = bot.db
        self.bot = bot
        self.db.bind_tables(Table)
        self.timer: asyncio.Task = self.loop.create_task(asyncio.sleep(0))
        self.loop.create_task(self.__init())

    def cog_check(self, ctx: BContext) -> bool:
        return ctx.guild is not None

    def cog_unload(self) -> None:
        self.timer.cancel()

    async def __init(self) -> None:
        await self.bot.wait_until_ready()
        for table in [Reminder, Recurring]:
            await table.create(if_not_exists=True)  # type: ignore
        async with self.db.get_session() as s:
            query = s.select(Reminder).order_by(Reminder.time, sort_order="desc")
            self.queue = [reminder async for reminder in await query.all()]
        await self.start_timer()

    @commands.group(invoke_without_command=True, usage="")
    async def remind(
        self,
        ctx: BContext,
        time: Time,
        *,
        topic: str = None,
    ) -> None:
        """Commands for setting and managing reminders."""
        await self.set_reminder(ctx, time, topic=topic)

    @remind.error
    async def remind_error(self, ctx: BContext, e: Exception) -> None:
        if ctx.invoked_subcommand is None:
            await self.set_reminder_error(ctx, e)

    @remind.command(name="set", aliases=["me"])
    async def set_reminder(
        self,
        ctx: BContext,
        time: Time,
        *,
        topic: str = None,
    ) -> None:
        """Have the bot remind you about something.
        First put time (in quotes if there are spaces), then topic"""
        time: Union[RecurringEvent, datetime] = time
        if topic is None and isinstance(time, RecurringEvent):
            await ctx.send("You must supply a message for a recurring reminder.")
            return
        if await self.process_reminder(ctx, time, topic):
            await ctx.send("Okay, I'll remind you.")

    @set_reminder.error
    async def set_reminder_error(self, ctx: BContext, e: Exception) -> None:
        if isinstance(e, (commands.BadArgument, commands.ConversionError)):
            await ctx.send(
                "Bad input. Valid input examples:\n"
                "remind 10m pizza\n"
                'remind "every week" call your mom'
            )
        else:
            await ctx.bot.handle_error(ctx, e)

    @remind.command(name="list")
    async def list_reminders(self, ctx: BContext) -> None:
        """List all reminders active for you in this server."""
        assert ctx.guild is not None
        pages = MenuKeysetPages(
            source=ReminderSource(ctx.bot.db, ctx.author.id, ctx.guild.id),
            clear_reactions_after=True,
        )
        try:
            await pages.start(ctx)
        except ValueError:
            await ctx.send("No reminders to show.")

    @remind.command(name="delete", aliases=["remove", "del", "cancel"])
    async def delete_reminder(self, ctx: BContext, reminder_id: int) -> None:
        """Delete a specific reminder. Use `list` to get IDs."""
        async with ctx.bot.db.get_session() as s:
            query = s.select(Reminder).where(Reminder.id == reminder_id)
            reminder = await query.first()
            if reminder is None:
                await ctx.send("No such reminder.")
                return
            if reminder.user_id != ctx.author.id:
                await ctx.send("That reminder belongs to someone else.")
                return
            await s.remove(reminder)
            await s.delete(Recurring).where(Recurring.id == reminder_id)

        if self.queue[-1] == reminder:
            self.timer.cancel()
            self.queue.pop()
            await self.start_timer()
        else:
            self.queue.remove(reminder)

        await ctx.send("Reminder deleted.")

    @remind.command(name="channel")
    @is_owner_or(manage_guild=True)
    async def set_channel(self, ctx: BContext, channel: TextChannel = None) -> None:
        """Set the channel reminders will appear in. Invoke with no input to reset."""
        assert ctx.guild is not None
        await ctx.bot.config.set_guild(
            ctx.guild.id, reminder_channel=channel and channel.id
        )
        if channel is None:
            destination = "the channel they were invoked in"
        else:
            destination = channel.mention
        await ctx.send(f"All reminders will be sent to {destination} from now on.")

    async def process_reminder(
        self,
        ctx: BContext,
        argument: Union[RecurringEvent, datetime],
        topic: Optional[str],
    ) -> bool:
        assert ctx.guild is not None

        if isinstance(argument, RecurringEvent):
            rr = rrule.rrulestr(argument.get_RFC_rrule())
            time = rr.after(datetime.now())
            next_ = rr.after(time)
            if next_ - time < MINIMUM_RECURRING_DELTA:
                await ctx.send(
                    "Recurring period too short. Minimum period is:\n"
                    f"{display_timedelta(MINIMUM_RECURRING_DELTA)}"
                )
                return False
        else:
            time = argument

        async with self.db.get_session() as s:
            reminder = await s.add(
                Reminder(
                    guild_id=ctx.guild.id,
                    channel_id=ctx.channel.id,
                    message_id=ctx.message.id,
                    user_id=ctx.author.id,
                    time=time,
                    topic=topic,
                )
            )
            if isinstance(argument, RecurringEvent):
                await s.add(Recurring(id=reminder.id, rrule=argument.get_RFC_rrule()))
        await self.schedule_reminder(reminder)
        return True

    async def schedule_reminder(self, reminder: Reminder) -> None:
        if not self.queue or reminder.time < self.queue[-1].time:
            self.queue.append(reminder)
            self.timer.cancel()
            await self.start_timer()
        else:
            reverse_insort_by_key(
                self.queue, reminder, key=lambda r: r.time, hi=len(self.queue) - 1
            )

    async def send_reminder(self, reminder: Reminder) -> None:
        found = False
        is_recurring = False
        if (
            (guild := self.bot.get_guild(reminder.guild_id))
            and (member := guild.get_member(reminder.user_id))
            and (
                channel := guild.get_channel(
                    (
                        reminder_channel_id := (
                            await self.bot.config.get_guild(guild.id)
                        ).get("reminder_channel")
                    )
                    or reminder.channel_id
                )
            )
        ):
            found = True
            assert isinstance(channel, TextChannel)
            async with self.db.get_session() as s:
                query = s.select(Recurring).where(Recurring.id == reminder.id)
                recurring = await query.first()
                is_recurring = recurring is not None

            reference = None
            if is_recurring:
                message = reminder.topic
            else:
                topic = reminder.topic or "something"
                message = f"You asked to be reminded about {topic}."
                if (
                    reminder_channel_id is None
                    or reminder_channel_id == reminder.channel_id
                ):
                    reference = discord.MessageReference(
                        message_id=reminder.message_id,
                        channel_id=reminder.channel_id,
                        guild_id=reminder.guild_id,
                    )
                if reference is None:
                    message = f"{member.mention}\n{message}"

            if member.permissions_in(channel).mention_everyone:
                allowed_mentions = AllowedMentions.all()
            else:
                allowed_mentions = AllowedMentions(
                    everyone=False, users=[member], roles=False
                )

            try:
                await channel.send(
                    message,
                    allowed_mentions=allowed_mentions,
                    reference=reference,
                )
            except (discord.NotFound, discord.Forbidden):
                pass
            except Exception as e:
                message = (
                    "An error occured in sending a reminder to "
                    f"{channel.guild.name}#{channel.name}"
                )
                self.bot.logger.exception(
                    message, exc_info=(type(e), e, e.__traceback__)
                )
            if is_recurring:
                rr = rrule.rrulestr(recurring.rrule)
                time = rr.after(reminder.time)
                async with self.db.get_session() as s:
                    await s.update(Reminder).set(Reminder.time, time).where(
                        Reminder.id == reminder.id
                    )
                reminder.time = time
                await self.schedule_reminder(reminder)
        if not is_recurring:
            async with self.db.get_session() as s:
                await s.remove(reminder)
                if not found:
                    await s.delete(Recurring).where(Recurring.id == reminder.id)

    async def start_timer(self) -> None:
        self.timer = self.loop.create_task(self.sleep())

    async def sleep(self) -> None:
        while self.queue:
            delta = (self.queue[-1].time - datetime.now()).total_seconds()
            if delta <= 0:
                await self.send_reminder(self.queue.pop())
            else:
                await asyncio.sleep(min(delta, 3_000_000))


def setup(bot: BeattieBot) -> None:
    bot.add_cog(Remind(bot))
