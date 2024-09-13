from __future__ import annotations

import asyncio
import copy
from collections import deque
from collections.abc import Mapping
from datetime import timedelta
from itertools import groupby
from operator import itemgetter
from typing import TYPE_CHECKING, Any, Self

from discord import Message, Thread
from discord.utils import sleep_until, snowflake_time, time_snowflake, utcnow

if TYPE_CHECKING:
    from beattie.bot import BeattieBot

    from .cog import Crosspost


MESSAGE_CACHE_TTL: int = 60 * 60 * 24  # one day in seconds


class Database:
    def __init__(self, bot: BeattieBot, cog: Crosspost):
        self.pool = bot.pool
        self.bot = bot
        self.cog = cog
        self._settings_cache: dict[tuple[int, int], Settings] = {}
        self._blacklist_cache: dict[int, set[str]] = {}
        self._expiry_deque: deque[int] = deque()
        self._message_cache: dict[int, list[int]] = {}
        self.overrides: dict[int, Settings] = {}

    async def async_init(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS public.crosspost (
                    guild_id bigint NOT NULL,
                    channel_id bigint NOT NULL,
                    auto boolean,
                    max_pages integer,
                    text boolean,
                    PRIMARY KEY(guild_id, channel_id)
                );

                CREATE TABLE IF NOT EXISTS public.crosspostmessage (
                    sent_message bigint NOT NULL PRIMARY KEY,
                    invoking_message bigint NOT NULL
                );

                CREATE INDEX IF NOT EXISTS crosspost_idx_invoking
                ON crosspostmessage (invoking_message);

                CREATE TABLE IF NOT EXISTS public.crosspostblacklist (
                    guild_id bigint NOT NULL,
                    site text NOT NULL,
                    PRIMARY KEY(guild_id, site)
                );
                """
            )

            rows = await conn.fetch(
                """
                SELECT *
                FROM crosspostmessage
                WHERE invoking_message > $1
                ORDER BY invoking_message
                """,
                time_snowflake(utcnow() - timedelta(seconds=MESSAGE_CACHE_TTL)),
            )

            for invoking_message, elems in groupby(
                rows,
                key=itemgetter("invoking_message"),
            ):
                self._expiry_deque.append(invoking_message)
                self._message_cache[invoking_message] = [
                    elem["sent_message"] for elem in elems
                ]
            self._expiry_task = asyncio.create_task(self._expire())

    async def _expire(self):
        try:
            while self._expiry_deque:
                entry = self._expiry_deque.popleft()
                until = snowflake_time(entry) + timedelta(seconds=MESSAGE_CACHE_TTL)
                await sleep_until(until)
                self._message_cache.pop(entry, None)
        except Exception:
            self.cog.logger.exception("Exception in message cache expiry task")

    async def get_effective_settings(self, message: Message) -> Settings:
        channel = message.channel

        out = Settings()

        if guild := message.guild:
            guild_id = guild.id
            out = out.apply(await self._get_settings(guild_id, 0))
            if category := getattr(channel, "category", None):
                out = out.apply(await self._get_settings(guild_id, category.id))
            if isinstance(channel, Thread):
                out = out.apply(await self._get_settings(guild_id, channel.parent_id))
        else:
            guild_id = 0

        out = out.apply(await self._get_settings(guild_id, channel.id))

        if guild is None:
            if out.auto is None:
                out.auto = True
            if out.max_pages is None:
                out.max_pages = 0
            if out.text is None:
                out.text = True

        if override := self.overrides.get(message.id):
            out = out.apply(override)

        return out

    async def _get_settings(self, guild_id: int, channel_id: int) -> Settings:
        try:
            return self._settings_cache[(guild_id, channel_id)]
        except KeyError:
            async with self.pool.acquire() as conn:
                config = await conn.fetchrow(
                    "SELECT * FROM crosspost WHERE guild_id = $1 AND channel_id = $2",
                    guild_id,
                    channel_id,
                )
            if config is None:
                res = Settings()
            else:
                res = Settings.from_record(config)
            self._settings_cache[(guild_id, channel_id)] = res
            return res

    async def set_settings(self, guild_id: int, channel_id: int, settings: Settings):
        if cached := self._settings_cache.get((guild_id, channel_id)):
            settings = cached.apply(settings)
        self._settings_cache[(guild_id, channel_id)] = settings
        kwargs = settings.asdict()
        cols = ",".join(kwargs)
        params = ",".join(f"${i}" for i, _ in enumerate(kwargs, 1))
        update = ",".join(f"{col}=EXCLUDED.{col}" for col in kwargs)
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO crosspost(guild_id,channel_id,{cols})
                VALUES({guild_id},{channel_id},{params})
                ON CONFLICT (guild_id,channel_id)
                DO UPDATE SET {update}
                """,
                *kwargs.values(),
            )

    async def clear_settings(self, guild_id: int, channel_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM crosspost WHERE guild_id = $1 AND channel_id = $2",
                guild_id,
                channel_id,
            )
        self._settings_cache.pop((guild_id, channel_id), None)

    async def clear_settings_all(self, guild_id: int):
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                "DELETE FROM crosspost WHERE guild_id = $1 RETURNING channel_id",
                guild_id,
            )

        for row in rows:
            self._settings_cache.pop((guild_id, row["channel_id"]), None)

    async def get_sent_messages(self, invoking_message: int) -> list[int]:
        if sent_messages := self._message_cache.get(invoking_message):
            return sent_messages
        elif (
            utcnow() - snowflake_time(invoking_message)
        ).total_seconds() > MESSAGE_CACHE_TTL - 3600:  # an hour's leeway
            async with self.pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM crosspostmessage WHERE invoking_message = $1",
                    invoking_message,
                )
                return [row["sent_message"] for row in rows]
        else:
            return []

    async def add_sent_message(self, invoking_message: int, sent_message: int):
        if (messages := self._message_cache.get(invoking_message)) is None:
            messages = []
            self._message_cache[invoking_message] = messages
            self._expiry_deque.append(invoking_message)
        messages.append(sent_message)
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO crosspostmessage(sent_message, invoking_message)
                VALUES ($1, $2)
                """,
                sent_message,
                invoking_message,
            )
        if self._expiry_task.done():
            self._expiry_task = asyncio.create_task(self._expire())

    async def del_sent_messages(self, invoking_message: int):
        self._message_cache.pop(invoking_message, None)
        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM crosspostmessage WHERE invoking_message = $1",
                invoking_message,
            )

    async def get_blacklist(self, guild_id: int) -> set[str]:
        try:
            return self._blacklist_cache[guild_id]
        except KeyError:
            res = set()
            async with self.pool.acquire() as conn:
                for row in await conn.fetch(
                    "SELECT * FROM crosspostblacklist WHERE guild_id = $1",
                    guild_id,
                ):
                    res.add(row["site"])

            self._blacklist_cache[guild_id] = res
            return res

    async def add_blacklist(self, guild_id: int, site: str) -> bool:
        blacklist = await self.get_blacklist(guild_id)
        if site in blacklist:
            return False

        async with self.pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO crosspostblacklist VALUES ($1, $2)",
                guild_id,
                site,
            )

        blacklist.add(site)

        return True

    async def del_blacklist(self, guild_id: int, site: str) -> bool:
        blacklist = await self.get_blacklist(guild_id)
        try:
            blacklist.remove(site)
        except KeyError:
            return False

        async with self.pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM crosspostblacklist WHERE guild_id = $1 AND site = $2",
                guild_id,
                site,
            )

        return True


class Settings:
    __slots__ = ("auto", "max_pages", "text")

    auto: bool | None
    max_pages: int | None
    text: bool | None

    def __init__(
        self,
        auto: bool = None,
        max_pages: int = None,
        text: bool = None,
    ):
        self.auto = auto
        self.max_pages = max_pages
        self.text = text

    def __str__(self) -> str:
        if self:
            return ", ".join(
                f"{k}={v}"
                for k in self.__slots__
                if (v := getattr(self, k)) is not None
            )
        else:
            return "(none)"

    def __eq__(self, other: Any) -> bool:
        if not isinstance(other, Settings):
            return NotImplemented
        return all(getattr(self, k) == getattr(other, k) for k in self.__slots__)

    def apply(self, other: Settings) -> Settings:
        """Returns a Settings with own values overwritten by non-None values of other"""
        out = copy.copy(self)
        for attr in self.__slots__:
            if (value := getattr(other, attr)) is not None:
                setattr(out, attr, value)

        return out

    def asdict(self) -> dict[str, Any]:
        return {k: v for k in self.__slots__ if (v := getattr(self, k)) is not None}

    def max_pages_or_default(self) -> int:
        match self.max_pages:
            case None:
                return 10
            case n:
                return n

    @classmethod
    def from_record(cls, row: Mapping[str, Any]) -> Self:
        return cls(*(row[attr] for attr in cls.__slots__))

    def __bool__(self):
        return any(getattr(self, k) is not None for k in self.__slots__)
