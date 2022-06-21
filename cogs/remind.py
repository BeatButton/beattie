import asyncio
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Optional, TypeVar

import discord
from dateutil import rrule
from discord import AllowedMentions, Embed
from discord.ext import commands
from discord.ext.commands import Cog
from recurrent.event_parser import RecurringEvent

from bot import BeattieBot
from context import BContext
from schema.remind import Recurring, Reminder, Table
from utils.checks import is_owner_or
from utils.converters import TimeConverter
from utils.etc import display_timedelta, reverse_insort_by_key
from utils.type_hints import GuildMessageable

MINIMUM_RECURRING_DELTA = timedelta(minutes=10)

T = TypeVar("T")


async def squash_unfindable(coro: Awaitable[T]) -> Optional[T]:
    try:
        return await coro
    except (discord.Forbidden, discord.NotFound):
        return None


class Remind(Cog):
    def __init__(self, bot: BeattieBot):
        self.queue: list[Reminder] = []
        self.db = bot.db
        self.bot = bot
        self.db.bind_tables(Table)  # type: ignore
        self.logger = logging.getLogger("beattie.remind")

    def cog_check(self, ctx: BContext) -> bool:
        return ctx.guild is not None

    async def cog_load(self) -> None:
        for table in [Reminder, Recurring]:
            await table.create(if_not_exists=True)  # type: ignore
        async with self.db.get_session() as s:
            query = s.select(Reminder).order_by(Reminder.time, sort_order="desc")
            self.queue = [reminder async for reminder in await query.all()]
        await self.start_timer()

    def cog_unload(self) -> None:
        self.timer.cancel()

    @commands.group(invoke_without_command=True, usage="")
    async def remind(
        self,
        ctx: BContext,
        time: RecurringEvent | datetime = commands.param(converter=TimeConverter),
        *,
        topic: str = None,
    ) -> None:
        """Commands for setting and managing reminders."""
        await self.set_reminder(ctx, time, topic=topic)

    @remind.error  # type: ignore
    async def remind_error(self, ctx: BContext, e: Exception) -> None:
        if ctx.invoked_subcommand is None:
            await self.set_reminder_error(ctx, e)  # type: ignore

    @remind.command(name="set", aliases=["me"])
    async def set_reminder(
        self,
        ctx: BContext,
        time: RecurringEvent | datetime = commands.param(converter=TimeConverter),
        *,
        topic: str = None,
    ) -> None:
        """Have the bot remind you about something.
        First put time (in quotes if there are spaces), then topic"""
        if topic is None and isinstance(time, RecurringEvent):
            await ctx.send("You must supply a message for a recurring reminder.")
            return
        if scheduled := await self.process_reminder(ctx, time, topic):
            msg = "Okay, I'll remind you"
            now = datetime.now()
            if scheduled.date() != now.date():
                msg = f"{msg} on {scheduled:%Y-%m-%d}"
            await ctx.send(f"{msg}.")

    @set_reminder.error  # type: ignore
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
        async with self.db.get_session() as s:
            query = (
                s.select(Reminder)
                .where(
                    (Reminder.user_id == ctx.author.id)
                    & (Reminder.guild_id == ctx.guild.id)  # type: ignore
                )
                .order_by(Reminder.id, sort_order="desc")
            )
            results = [reminder async for reminder in await query.all()]
        if results:
            embed = Embed(
                description="\n".join(
                    f'ID {row.id}: "{row.topic}" at {row.time}' for row in results
                )
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("No reminders found.")

    @remind.command(name="delete", aliases=["remove", "del", "cancel"])
    async def delete_reminder(self, ctx: BContext, reminder_id: int) -> None:
        """Delete a specific reminder. Use `list` to get IDs."""
        async with ctx.bot.db.get_session() as s:
            query = s.select(Reminder).where(Reminder.id == reminder_id)  # type: ignore
            reminder = await query.first()
            if reminder is None:
                await ctx.send("No such reminder.")
                return
            if reminder.user_id != ctx.author.id:  # type: ignore
                await ctx.send("That reminder belongs to someone else.")
                return
            await s.remove(reminder)
            await s.delete(Recurring).where(Recurring.id == reminder_id)  # type: ignore

        if self.queue[-1] == reminder:
            self.timer.cancel()
            self.queue.pop()
            await self.start_timer()
        else:
            self.queue.remove(reminder)  # type: ignore

        await ctx.send("Reminder deleted.")

    @remind.command(name="channel")
    @is_owner_or(manage_guild=True)
    async def set_channel(
        self, ctx: BContext, channel: GuildMessageable = None
    ) -> None:
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
        argument: RecurringEvent | datetime,
        topic: Optional[str],
    ) -> Optional[datetime]:
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
                return None
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
                await s.add(
                    Recurring(
                        id=reminder.id, rrule=argument.get_RFC_rrule()  # type: ignore
                    )
                )
        await self.schedule_reminder(reminder)  # type: ignore
        return time

    async def schedule_reminder(self, reminder: Reminder) -> None:
        if not self.queue or reminder.time < self.queue[-1].time:
            self.queue.append(reminder)
            self.timer.cancel()
            await self.start_timer()
        else:
            reverse_insort_by_key(
                self.queue,
                reminder,
                key=lambda r: r.time,  # type: ignore
                hi=len(self.queue) - 1,
            )

    async def send_reminder(self, reminder: Reminder) -> None:
        self.logger.info(f"handling reminder {reminder}")
        found = False
        is_recurring = False
        guild_id: int = reminder.guild_id  # type: ignore
        user_id: int = reminder.user_id  # type: ignore
        channel_id: int = reminder.channel_id  # type: ignore
        if (
            (
                guild := self.bot.get_guild(guild_id)
                or await squash_unfindable(self.bot.fetch_guild(guild_id))
            )
            and (
                member := guild.get_member(user_id)
                or await squash_unfindable(guild.fetch_member(user_id))
            )
            and (
                channel := guild.get_channel_or_thread(
                    (
                        reminder_channel_id := (
                            await self.bot.config.get_guild(guild.id)
                        ).get("reminder_channel")
                        or channel_id
                    )
                )
                or await squash_unfindable(guild.fetch_channel(reminder_channel_id))
            )
        ):
            found = True
            assert isinstance(channel, GuildMessageable)
            async with self.db.get_session() as s:
                query = s.select(Recurring).where(
                    Recurring.id == reminder.id  # type: ignore
                )
                recurring = await query.first()
                is_recurring = recurring is not None

            self.logger.info(f"reminder {reminder.id} found, recurring={is_recurring}")

            reference = None
            message: str
            if is_recurring:
                message = reminder.topic  # type: ignore
            else:
                topic = reminder.topic or "something"
                message = f"You asked to be reminded about {topic}."
                if reminder_channel_id == reminder.channel_id:
                    try:
                        await channel.fetch_message(reminder.message_id)  # type: ignore
                    except (discord.NotFound, discord.Forbidden):
                        pass
                    else:
                        reference = discord.MessageReference(
                            message_id=reminder.message_id,  # type: ignore
                            channel_id=reminder.channel_id,  # type: ignore
                            guild_id=reminder.guild_id,  # type: ignore
                        )
                if reference is None:
                    message = f"{member.mention}\n{message}"

            if channel.permissions_for(member).mention_everyone:
                allowed_mentions = AllowedMentions.all()
            else:
                allowed_mentions = AllowedMentions.none().merge(
                    AllowedMentions(replied_user=True)
                )

            kwargs = {"allowed_mentions": allowed_mentions, "reference": reference}
            try:
                await channel.send(message, **kwargs)
            except discord.Forbidden:
                pass
            except Exception as e:
                message = (
                    "An error occured in sending a reminder to "
                    f"{channel.guild.name}#{channel.name}"
                )
                self.logger.exception(message, exc_info=(type(e), e, e.__traceback__))
            self.logger.info(f"reminder {reminder.id} was sent")
            if is_recurring:
                rr = rrule.rrulestr(recurring.rrule, dtstart=reminder.time)
                time = rr.after(reminder.time)
                async with self.db.get_session() as s:
                    await s.update(Reminder).set(Reminder.time, time).where(
                        Reminder.id == reminder.id  # type: ignore
                    )
                reminder.time = time
                await self.schedule_reminder(reminder)
        else:
            self.logger.info(f"reminder {reminder.id} could not be resolved")
        if not is_recurring:
            async with self.db.get_session() as s:
                await s.remove(reminder)
                if not found:
                    await s.delete(Recurring).where(
                        Recurring.id == reminder.id  # type: ignore
                    )

    async def start_timer(self) -> None:
        self.timer = asyncio.create_task(self.sleep())

    async def sleep(self) -> None:
        while self.queue:
            reminder_time: datetime = self.queue[-1].time  # type: ignore
            delta = (reminder_time - datetime.now()).total_seconds()
            if delta <= 0:
                try:
                    await self.send_reminder(self.queue.pop())
                except Exception as e:
                    self.logger.exception(
                        "Error sending reminder", exc_info=(type(e), e, e.__traceback__)
                    )
            else:
                self.logger.info(f"sleeping for {delta} seconds")
                await asyncio.sleep(delta)


async def setup(bot: BeattieBot) -> None:
    await bot.add_cog(Remind(bot))
