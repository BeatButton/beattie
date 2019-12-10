from schema.config import Channel, Guild, Member, Table
from utils.asyncqlio import to_dict


class Config:
    def __init__(self, bot):
        self.db = bot.db
        self.bot = bot
        self.db.bind_tables(Table)
        bot.loop.create_task(self.__init())
        self._cache = {"member": {}, "channel": {}}

    async def __init(self):
        await self.bot.wait_until_ready()
        for table in [Guild, Member, Channel]:
            await table.create(if_not_exists=True)

    async def get_guild(self, guild_id):
        try:
            return self._cache[guild_id]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Guild).where(Guild.id == guild_id)
                guild = await query.first()
            if guild is None:
                res = {"id": guild_id}
            else:
                res = to_dict(guild)
            self._cache[guild_id] = res
            return res

    async def set_guild(self, guild_id, **kwargs):
        guild = await self.get_guild(guild_id)
        self._cache[guild_id].update(kwargs)
        async with self.db.get_session() as s:
            row = Guild(**{**guild, **kwargs})
            query = s.insert.rows(row)
            query = query.on_conflict(Guild.id).update(
                getattr(Guild, name) for name in kwargs
            )
            await query.run()

    async def remove_guild(self, gid):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            if guild is not None:
                await s.remove(guild)
            await s.delete(Member).where(Member.guild_id == gid)
            await s.delete(Channel).where(Channel.guild_id == gid)
        self._cache.pop(gid, None)
        self._cache["member"].pop(gid, None)
        self._cache["channel"].pop(gid, None)

    async def get_member(self, guild_id, user_id):
        try:
            return self._cache["member"].setdefault(guild_id, {})[user_id]
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
            self._cache["member"][guild_id][user_id] = ret
            return ret

    async def set_member(self, guild_id, user_id, **kwargs):
        member = await self.get_member(guild_id, user_id)
        self._cache["member"][guild_id][user_id].update(kwargs)
        async with self.db.get_session() as s:
            row = Member(**{**member, **kwargs})
            query = s.insert.rows(row)
            query = query.on_conflict(Member.id, Member.guild_id).update(
                getattr(Member, name) for name in kwargs
            )
            await query.run()

    async def get_channel(self, guild_id, channel_id):
        try:
            return self._cache["channel"].setdefault(guild_id, {})[channel_id]
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
            self._cache["channel"][guild_id][channel_id] = ret
            return ret

    async def set_channel(self, guild_id, channel_id, **kwargs):
        channel = await self.get_channel(guild_id, channel_id)
        self._cache["channel"][guild_id][channel_id].update(kwargs)
        async with self.db.get_session() as s:
            row = Channel(**{**channel, **kwargs})
            query = s.insert.rows(row)
            query = query.on_conflict(Channel.id).update(
                getattr(Channel, name) for name in kwargs
            )
            await query.run()
