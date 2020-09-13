import asyncio
from datetime import datetime
from typing import Any, Iterable, List, Optional

from asyncqlio.db import DatabaseInterface
from discord import AllowedMentions, Embed, TextChannel
from discord.ext import commands, menus
from discord.ext.commands import Cog
from discord.ext.menus import MenuKeysetPages, PageDirection, PageSpecifier

from bot import BeattieBot
from context import BContext
from schema.remind import Reminder, Table
from utils.checks import is_owner_or
from utils.converters import Time
from utils.etc import reverse_insort_by_key


class ReminderSource(menus.KeysetPageSource):
    def __init__(self, db: DatabaseInterface, user_id: int, guild_id: int):
        self.db = db
        self.user_id = user_id
        self.guild_id = guild_id

    def is_paginating(self) -> bool:
        return True

    async def get_page(self, specifier: PageSpecifier) -> List[Reminder]:
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
        self.queue: List[Reminder] = []
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
        await Reminder.create(if_not_exists=True)
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
        topic: Optional[commands.clean_content] = None,
    ) -> None:
        """Commands for setting and managing reminders."""
        await self.set_reminder(ctx, time, topic=topic)

    @remind.error
    async def remind_error(self, ctx: BContext, e: Exception) -> None:
        if ctx.invoked_subcommand is None:
            await self.set_reminder_error(ctx, e)

    @remind.command(name="set")
    async def set_reminder(
        self, ctx: BContext, time: Time, *, topic: Optional[str] = None,
    ) -> None:
        """Have the bot remind you about something.
           First put time (in quotes if there are spaces), then topic"""
        await self.schedule_reminder(ctx, time, topic)
        await ctx.send("Okay, I'll remind you.")

    @set_reminder.error
    async def set_reminder_error(self, ctx: BContext, e: Exception) -> None:
        if isinstance(e, (commands.BadArgument, commands.ConversionError)):
            await ctx.send(
                "Bad input. Valid input examples:\n"
                "remind 10m pizza\n"
                'remind "two days" check progress'
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

        if self.queue[-1] == reminder:
            self.timer.cancel()
            self.queue.pop()
            await self.start_timer()
        else:
            self.queue.remove(reminder)

        await ctx.send("Reminder deleted.")

    @remind.command(name="channel")
    @is_owner_or(manage_guild=True)
    async def set_channel(
        self, ctx: BContext, channel: Optional[TextChannel] = None
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

    async def schedule_reminder(
        self, ctx: BContext, time: Time, topic: Optional[str]
    ) -> None:
        assert ctx.guild is not None
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

    async def send_reminder(self, reminder: Reminder) -> None:
        if (
            (guild := self.bot.get_guild(reminder.guild_id))
            and (member := guild.get_member(reminder.user_id))
            and (
                channel := guild.get_channel(
                    (await self.bot.config.get_guild(guild.id)).get("reminder_channel")
                    or reminder.channel_id
                )
            )
        ):
            assert isinstance(channel, TextChannel)
            topic = reminder.topic or "something"
            message = f"{member.mention}\nYou asked to be reminded about {topic}."
            await channel.send(
                message,
                allowed_mentions=AllowedMentions(
                    everyone=False, users=False, roles=False
                ),
            )
        async with self.db.get_session() as s:
            await s.remove(reminder)

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
