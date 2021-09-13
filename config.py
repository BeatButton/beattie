from __future__ import annotations

from typing import TYPE_CHECKING, Any

from schema.config import Guild, Table
from utils.asyncqlio import to_dict

if TYPE_CHECKING:
    from bot import BeattieBot


class Config:
    def __init__(self, bot: BeattieBot):
        self.db = bot.db
        self.bot = bot
        self.db.bind_tables(Table)  # type: ignore
        bot.loop.create_task(self.__init())
        self._cache: dict[int, dict[str, Any]] = {}

    async def __init(self) -> None:
        await self.bot.wait_until_ready()
        await Guild.create(if_not_exists=True)

    async def get_guild(self, guild_id: int) -> dict[str, Any]:
        try:
            return self._cache[guild_id]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Guild).where(Guild.id == guild_id)  # type: ignore
                guild = await query.first()
            if guild is None:
                res = {"id": guild_id}
            else:
                res = to_dict(guild)
            self._cache[guild_id] = res
            return res

    async def set_guild(self, guild_id: int, **kwargs: Any) -> None:
        guild = await self.get_guild(guild_id)
        self._cache[guild_id].update(kwargs)
        async with self.db.get_session() as s:
            row = Guild(**{**guild, **kwargs})
            query = s.insert.rows(row)
            query = query.on_conflict(Guild.id).update(
                getattr(Guild, name) for name in kwargs  # type: ignore
            )
            await query.run()
