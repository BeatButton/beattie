from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from operator import attrgetter
from typing import TYPE_CHECKING, Any, Mapping, Self, TypeVar
from zoneinfo import ZoneInfo

import discord
from dateutil import rrule
from discord import AllowedMentions, DMChannel, Embed
from discord.ext import commands
from discord.ext.commands import Cog
from discord.utils import format_dt
from recurrent.event_parser import RecurringEvent

from beattie.utils.aioutils import squash_unfindable
from beattie.utils.checks import is_owner_or
from beattie.utils.converters import TimeConverter, TimezoneConverter
from beattie.utils.etc import UTC, display_timedelta, reverse_insort_by_key
from beattie.utils.type_hints import GuildMessageable

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext

MINIMUM_RECURRING_DELTA = timedelta(minutes=10)

T = TypeVar("T")


class Reminder:
    __slots__ = (
        "id",
        "guild_id",
        "channel_id",
        "message_id",
        "user_id",
        "time",
        "topic",
    )
    id: int
    guild_id: int
    channel_id: int
    message_id: int
    user_id: int
    time: datetime
    topic: str

    def __init__(
        self,
        id: int,
        guild_id: int,
        channel_id: int,
        message_id: int,
        user_id: int,
        time: datetime,
        topic: str,
    ):
        self.id = id
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.message_id = message_id
        self.user_id = user_id
        self.time = time
        self.topic = topic

    def __eq__(self, other: Any):
        if not isinstance(other, Reminder):
            return NotImplemented
        return self.id == other.id

    def __repr__(self) -> str:
        slots = ", ".join(f"{slot}={getattr(self, slot)!r}" for slot in self.__slots__)
        return f"{type(self).__name__}({slots})"

    def asdict(self) -> dict[str, Any]:
        return {k: v for k in self.__slots__ if (v := getattr(self, k)) is not None}

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> Self:
        return cls(*(row[attr] for attr in cls.__slots__))


class Remind(Cog):
    def __init__(self, bot: BeattieBot):
        self.queue: list[Reminder] = []
        self.pool = bot.pool
        self.bot = bot
        self.logger = logging.getLogger(__name__)

    async def cog_load(self):
        async with self.pool.acquire() as conn:
            user = self.bot.user
            assert user is not None
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public.reminder (
                    id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    bot_id bigint NOT NULL,
                    guild_id bigint NOT NULL,
                    channel_id bigint NOT NULL,
                    message_id bigint NOT NULL,
                    user_id bigint NOT NULL,
                    "time" timestamp without time zone NOT NULL,
                    topic text
                );

                CREATE TABLE IF NOT EXISTS public.recurring (
                    id integer PRIMARY KEY
                        REFERENCES public.reminder(id) ON DELETE CASCADE,
                    rrule text NOT NULL
                );

                CREATE TABLE IF NOT EXISTS public.timezone (
                    user_id bigint NOT NULL PRIMARY KEY,
                    timezone text NOT NULL
                );
                """
            )
            self.queue = [
                Reminder.from_record(row)
                for row in await conn.fetch(
                    "SELECT * FROM reminder WHERE bot_id = $1 ORDER BY time DESC",
                    user.id,
                )
            ]
        await self.start_timer()

    def cog_unload(self):
        self.timer.cancel()

    @Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        user = self.bot.user
        assert user is not None
        others = self.bot.shared.bot_ids - {user.id}
        if any(m.id in others for m in guild.members):
            return
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE reminder SET bot_id = $1 WHERE guild_id = $2;",
                user.id,
                guild.id,
            )

    async def get_user_timezone(self, user_id: int) -> ZoneInfo | None:
        async with self.pool.acquire() as conn:
            tz = await conn.fetchval(
                "SELECT timezone FROM timezone WHERE user_id = $1", user_id
            )
        if tz:
            return ZoneInfo(tz)

    @commands.group(invoke_without_command=True, usage="")
    async def remind(
        self,
        ctx: BContext,
        time: RecurringEvent | datetime = commands.param(converter=TimeConverter),
        *,
        topic: str = None,
    ):
        """Commands for setting and managing reminders."""
        await self.set_reminder(ctx, time, topic=topic)

    @remind.error
    async def remind_error(self, ctx: BContext, e: Exception):
        if ctx.invoked_subcommand is None:
            await self.set_reminder_error(ctx, e)

    @remind.command(name="set", aliases=["me"])
    async def set_reminder(
        self,
        ctx: BContext,
        time: RecurringEvent | datetime = commands.param(converter=TimeConverter),
        *,
        topic: str = None,
    ):
        """Have the bot remind you about something.
        First put time (in quotes if there are spaces), then topic"""
        if topic is None and isinstance(time, RecurringEvent):
            await ctx.send("You must supply a message for a recurring reminder.")
            return
        tz = (await self.get_user_timezone(ctx.author.id)) or UTC
        if scheduled := await self.process_reminder(ctx, time, topic, tz):
            await ctx.send(f"Okay, reminder scheduled for {format_dt(scheduled)}.")

    @set_reminder.error
    async def set_reminder_error(self, ctx: BContext, e: Exception):
        if isinstance(e, (commands.BadArgument, commands.ConversionError)):
            invoked = ctx.invoked_parents or []
            if ctx.invoked_subcommand:
                assert ctx.subcommand_passed is not None
                invoked.append(ctx.subcommand_passed)
            command_str = "{}{}".format(
                ctx.prefix or "",
                " ".join(invoked),
            )
            await ctx.send(
                "Bad input. Valid input examples:\n"
                f"{command_str} 10m pizza\n"
                f'{command_str} "every week" call your mom'
            )
        else:
            await ctx.bot.handle_error(ctx, e)

    @remind.command(name="list")
    async def list_reminders(self, ctx: BContext):
        """List all reminders active for you in this server."""
        if guild := ctx.guild:
            guild_id = guild.id
        else:
            guild_id = ctx.channel.id
        tz = (await self.get_user_timezone(ctx.author.id)) or UTC
        async with self.pool.acquire() as conn:
            rows = [
                Reminder.from_record(row)
                for row in await conn.fetch(
                    """
                    SELECT * FROM reminder
                    WHERE user_id = $1 AND guild_id = $2
                    ORDER BY id DESC
                    """,
                    ctx.author.id,
                    guild_id,
                )
            ]
        if rows:
            embed = Embed(
                description="\n".join(
                    f'ID {row.id}: "{row.topic}" at {row.time.astimezone(tz)}'
                    for row in rows
                )
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("No reminders found.")

    @remind.command(name="delete", aliases=["remove", "del", "cancel"])
    async def delete_reminder(self, ctx: BContext, reminder_id: int):
        """Delete a specific reminder. Use `list` to get IDs."""
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(
                "SELECT * FROM reminder WHERE id = $1", reminder_id
            )
            if record is None:
                await ctx.send("No such reminder.")
                return
            reminder = Reminder.from_record(record)
            if reminder.user_id != ctx.author.id:
                await ctx.send("That reminder belongs to someone else.")
                return

            await conn.execute(
                "DELETE FROM reminder WHERE id = $1",
                reminder.id,
            )

        if self.queue[-1] == reminder:
            self.timer.cancel()
            self.queue.pop()
            await self.start_timer()
        else:
            self.queue.remove(reminder)

        await ctx.send("Reminder deleted.")

    @remind.command(name="channel")
    @commands.check(lambda ctx: ctx.guild is not None)
    @is_owner_or(manage_guild=True)
    async def set_channel(self, ctx: BContext, channel: GuildMessageable = None):
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
        topic: str | None,
        tz: ZoneInfo,
    ) -> datetime | None:
        now = datetime.now(tz)

        if guild := ctx.guild:
            guild_id = guild.id
        else:
            guild_id = ctx.channel.id

        rrule_str = None
        if isinstance(argument, RecurringEvent):
            rrule_str = argument.get_RFC_rrule()
            rr = rrule.rrulestr(rrule_str)
            time: datetime | None = rr.after(now.astimezone().replace(tzinfo=None))
            if time is None:
                raise RuntimeError("rr.after returned None")
            next_ = rr.after(time)
            if next_ - time < MINIMUM_RECURRING_DELTA:
                await ctx.send(
                    "Recurring period too short. Minimum period is:\n"
                    f"{display_timedelta(MINIMUM_RECURRING_DELTA)}"
                )
                return None
            time = time.replace(tzinfo=tz)
        else:
            time = argument

        user = self.bot.user
        assert user is not None
        async with self.pool.acquire() as conn:
            record = await conn.fetchrow(
                """
                INSERT INTO reminder(
                    bot_id,
                    guild_id,
                    channel_id,
                    message_id,
                    user_id,
                    time,
                    topic
                ) VALUES (
                    $1, $2, $3, $4, $5, $6, $7
                )
                RETURNING *
                """,
                user.id,
                guild_id,
                ctx.channel.id,
                ctx.message.id,
                ctx.author.id,
                time.astimezone().replace(tzinfo=None),
                topic,
            )
            assert record is not None
            reminder = Reminder.from_record(record)
            if isinstance(argument, RecurringEvent):
                assert isinstance(rrule_str, str)
                await conn.execute(
                    "INSERT INTO recurring(id, rrule) VALUES ($1, $2)",
                    reminder.id,
                    rrule_str,
                )
        await self.schedule_reminder(reminder)
        return time

    async def schedule_reminder(self, reminder: Reminder):
        if not self.queue or reminder.time < self.queue[-1].time:
            self.queue.append(reminder)
            self.timer.cancel()
            await self.start_timer()
        else:
            reverse_insort_by_key(
                self.queue,
                reminder,
                key=attrgetter("time"),
                hi=len(self.queue) - 1,
            )

    async def send_reminder(self, reminder: Reminder):
        self.logger.info(f"handling reminder {reminder}")
        recurring = None
        guild_id = reminder.guild_id
        user_id = reminder.user_id
        channel_id = reminder.channel_id
        reminder_channel_id = channel_id
        guild = None

        if guild_id == channel_id:
            guild_id = None
            channel = await squash_unfindable(self.bot.fetch_channel(channel_id))
            assert isinstance(channel, DMChannel)
            recipient = channel.recipient
            assert recipient is not None
        elif guild := await squash_unfindable(self.bot.fetch_guild(guild_id)):
            recipient = await squash_unfindable(guild.fetch_member(user_id))

            if recipient:
                reminder_channel_id = (await self.bot.config.get_guild(guild.id)).get(
                    "reminder_channel"
                ) or channel_id

                channel = guild.get_channel_or_thread(
                    reminder_channel_id
                ) or await squash_unfindable(guild.fetch_channel(reminder_channel_id))

        else:
            channel = None

        if channel and recipient:
            assert isinstance(channel, (GuildMessageable, DMChannel))
            async with self.pool.acquire() as conn:
                recurring = await conn.fetchrow(
                    "SELECT * FROM recurring WHERE id = $1", reminder.id
                )

            self.logger.info(
                f"reminder {reminder.id} found, recurring={recurring is not None}"
            )

            reference = None
            message: str
            if recurring is not None:
                message = reminder.topic
            else:
                topic = reminder.topic or "something"
                message = f"You asked to be reminded about {topic}."
                if reminder_channel_id == channel_id:
                    message_id: int = reminder.message_id
                    reference = await squash_unfindable(
                        channel.fetch_message(message_id)
                    ) and discord.MessageReference(
                        message_id=message_id,
                        channel_id=channel_id,
                        guild_id=guild_id,
                    )
                if reference is None:
                    message = f"{recipient.mention}\n{message}"

            if (
                isinstance(recipient, discord.User)
                or isinstance(channel, discord.Thread)
                or channel.permissions_for(recipient).mention_everyone
            ):
                allowed_mentions = AllowedMentions.all()
            else:
                allowed_mentions = AllowedMentions.none().merge(
                    AllowedMentions(replied_user=True, users=[recipient])
                )

            kwargs = {"allowed_mentions": allowed_mentions, "reference": reference}
            try:
                await channel.send(message, **kwargs)
            except discord.Forbidden:
                pass
            except Exception:
                if guild:
                    assert isinstance(channel, GuildMessageable)
                    chan = f"{guild.name}#{channel.name}"
                else:
                    chan = f"DM with {recipient.name}"
                message = f"An error occured in sending a reminder to {chan}"
                self.logger.exception(message)
            self.logger.info(f"reminder {reminder.id} was sent")
            if recurring is not None:
                rr = rrule.rrulestr(recurring["rrule"], dtstart=reminder.time)
                time = rr.after(reminder.time)
                async with self.pool.acquire() as conn:
                    await conn.execute(
                        "UPDATE reminder SET time = $1 WHERE id = $2",
                        time,
                        reminder.id,
                    )
                reminder.time = time
                await self.schedule_reminder(reminder)
        else:
            self.logger.info(f"reminder {reminder.id} could not be resolved")
        if recurring is None:
            async with self.pool.acquire() as conn:
                await conn.execute("DELETE FROM reminder WHERE id = $1", reminder.id)

    async def start_timer(self):
        self.timer = asyncio.create_task(self.sleep())

    async def sleep(self):
        while self.queue:
            reminder_time: datetime = self.queue[-1].time
            delta = (reminder_time - datetime.now()).total_seconds()
            if delta <= 0:
                try:
                    await self.send_reminder(self.queue.pop())
                except Exception:
                    self.logger.exception("Error sending reminder")
            else:
                self.logger.info(f"sleeping for {delta} seconds")
                await asyncio.sleep(delta)

    @commands.group(invoke_without_command=True, usage="", aliases=["tz"])
    async def timezone(
        self,
        ctx: BContext,
        *,
        timezone: ZoneInfo | None = commands.param(
            converter=TimezoneConverter, default=None
        ),
    ):
        """Commands for managing your timezone."""
        if timezone:
            await self.set_timezone(ctx, timezone=timezone)
        else:
            await self.get_timezone(ctx)

    @timezone.command(name="get")
    async def get_timezone(self, ctx: BContext):
        """Get your timezone."""
        tz = await self.get_user_timezone(ctx.author.id)
        if tz is None:
            await ctx.send("You have not set a timezone. Your reminders will use UTC.")
        else:
            await ctx.send(f"Your timezone is {tz}.")

    @timezone.command(name="set")
    async def set_timezone(
        self,
        ctx: BContext,
        *,
        timezone: ZoneInfo = commands.param(converter=TimezoneConverter),
    ):
        """Set your timezone.

        A full list of timezones can be found at \
<https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List>"""
        tz = timezone.key
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO timezone(user_id, timezone)
                VALUES ($1, $2)
                ON CONFLICT (user_id)
                DO UPDATE SET timezone=EXCLUDED.timezone
                """,
                ctx.author.id,
                tz,
            )
        await ctx.send(f"Your timezone has been set to {tz}.")

    @timezone.command(name="unset")
    async def unset_timezone(self, ctx: BContext):
        """Unset your timezone."""
        async with self.pool.acquire() as conn:
            await conn.execute("DELETE FROM timezone WHERE user_id = $1", ctx.author.id)

        await ctx.send("I have forgotten your timezone.")


async def setup(bot: BeattieBot):
    await bot.add_cog(Remind(bot))
