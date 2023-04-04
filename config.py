from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from bot import BeattieBot


class Config:
    def __init__(self, bot: BeattieBot):
        self.pool = bot.pool
        self.bot = bot
        self._cache: dict[int, dict[str, Any]] = {}

    async def async_init(self):
        async with self.pool.acquire() as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS
                public.guild (
                    id bigint PRIMARY KEY NOT NULL,
                    cog_blacklist text,
                    prefix text,
                    reminder_channel bigint
                );"""
            )

    async def get_guild(self, guild_id: int) -> Mapping[str, Any]:
        try:
            return self._cache[guild_id]
        except KeyError:
            async with self.pool.acquire() as conn:
                guild = await conn.fetchrow(
                    "SELECT * FROM guild WHERE guild.id = $1", guild_id
                )
            if guild is None:
                guild = {"id": guild_id}
            else:
                guild = dict(guild)
            self._cache[guild_id] = guild
            return guild

    async def set_guild(self, guild_id: int, **kwargs: Any):
        self._cache[guild_id].update(kwargs)
        cols = ",".join(kwargs)
        params = ",".join(f"${i}" for i, _ in enumerate(kwargs, 1))
        update = ",".join(f"{col}=EXCLUDED.{col}" for col in kwargs)
        async with self.pool.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO guild(id,{cols})
                VALUES({guild_id},{params})
                ON CONFLICT (id)
                DO UPDATE SET {update}
                """,
                *kwargs.values(),
            )
