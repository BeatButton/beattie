from __future__ import annotations  #  type: ignore

from typing import Any, Dict, Union

from schema.config import Channel, Guild, Member, Table  # type: ignore
from utils.asyncqlio import to_dict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bot import BeattieBot


class Config:
    def __init__(self, bot: BeattieBot):
        self.db = bot.db
        self.bot = bot
        self.db.bind_tables(Table)
        bot.loop.create_task(self.__init())
        self._guild_cache: Dict[int, Dict[str, Any]] = {}
        self._member_cache: Dict[int, Dict[int, Dict[str, Any]]] = {}
        self._channel_cache: Dict[int, Dict[int, Dict[str, Any]]] = {}

    async def __init(self) -> None:
        await self.bot.wait_until_ready()
        for table in [Guild, Member, Channel]:
            await table.create(if_not_exists=True)

    async def get_guild(self, guild_id: int) -> Dict[str, Any]:
        try:
            return self._guild_cache[guild_id]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Guild).where(Guild.id == guild_id)
                guild = await query.first()
            if guild is None:
                res = {"id": guild_id}
            else:
                res = to_dict(guild)
            self._guild_cache[guild_id] = res
            return res

    async def set_guild(self, guild_id: int, **kwargs: Any) -> None:
        guild = await self.get_guild(guild_id)
        self._guild_cache[guild_id].update(kwargs)
        async with self.db.get_session() as s:
            row = Guild(**{**guild, **kwargs})
            query = s.insert.rows(row)
            query = query.on_conflict(Guild.id).update(
                getattr(Guild, name) for name in kwargs
            )
            await query.run()

    async def remove_guild(self, gid: int) -> None:
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            if guild is not None:
                await s.remove(guild)
            await s.delete(Member).where(Member.guild_id == gid)
            await s.delete(Channel).where(Channel.guild_id == gid)
        self._guild_cache.pop(gid, None)
        self._member_cache.pop(gid, None)
        self._channel_cache.pop(gid, None)

    async def get_member(self, guild_id: int, user_id: int) -> Dict[str, Any]:
        try:
            return self._member_cache.setdefault(guild_id, {})[user_id]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Member).where(
                    (Member.id == user_id) & (Member.guild_id == guild_id)
                )
                member = await query.first()
            if member is None:
                ret = {"guild_id": guild_id, "id": user_id}
            else:
                ret = to_dict(member)
            self._member_cache[guild_id][user_id] = ret
            return ret

    async def set_member(self, guild_id: int, user_id: int, **kwargs: Any) -> None:
        member = await self.get_member(guild_id, user_id)
        self._member_cache[guild_id][user_id].update(kwargs)
        async with self.db.get_session() as s:
            row = Member(**{**member, **kwargs})
            query = s.insert.rows(row)
            query = query.on_conflict(Member.id, Member.guild_id).update(
                getattr(Member, name) for name in kwargs
            )
            await query.run()

    async def get_channel(self, guild_id: int, channel_id: int) -> Dict[str, Any]:
        try:
            return self._channel_cache.setdefault(guild_id, {})[channel_id]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Channel).where(
                    (Channel.id == channel_id) & (Channel.guild_id == guild_id)
                )
                channel = await query.first()
            if channel is None:
                ret = {"guild_id": guild_id, "id": channel_id}
            else:
                ret = to_dict(channel)
            self._channel_cache[guild_id][channel_id] = ret
            return ret

    async def set_channel(self, guild_id: int, channel_id: int, **kwargs: Any) -> None:
        channel = await self.get_channel(guild_id, channel_id)
        self._channel_cache[guild_id][channel_id].update(kwargs)
        async with self.db.get_session() as s:
            row = Channel(**{**channel, **kwargs})
            query = s.insert.rows(row)
            query = query.on_conflict(Channel.id).update(
                getattr(Channel, name) for name in kwargs
            )
            await query.run()
