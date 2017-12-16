from schema.config import Table, Guild, Member, Channel
from utils.asyncqlio import to_dict


class Config:
    def __init__(self, bot):
        self.db = bot.db
        self.db.bind_tables(Table)
        bot.loop.create_task(self.__init(bot))
        self._cache = {}
        self._cache['member'] = {}
        self._cache['channel'] = {}

    async def __init(self, bot):
        await bot.wait_until_ready()
        for table in [Guild, Member, Channel]:
            await table.create(if_not_exists=True)

    async def get(self, gid):
        try:
            return self._cache[gid]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Guild).where(Guild.id == gid)
                guild = await query.first()
            if guild is None:
                res = {'id': gid}
            else:
                res = to_dict(guild)
            self._cache[gid] = res
            return res

    async def set(self, gid, **kwargs):
        async with self.db.get_session() as s:
            row = Guild(id=gid, **kwargs)
            query = s.insert.rows(row)
            query = query.on_conflict(Guild.id).update(getattr(Guild, name) for name in kwargs)
            await query.run()
        try:
            self._cache[gid].update(kwargs)
        except KeyError:
            pass

    async def remove(self, gid):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            if guild is not None:
                await s.remove(guild)
            await s.delete(Member).where(Member.guild_id == gid)
            await s.delete(Channel).where(Channel.guild_id == gid)
        self._cache.pop(gid, None)
        self._cache['member'].pop(gid, None)
        self._cache['channel'].pop(gid, None)

    async def update_member(self, gid, uid, **kwargs):
        async with self.db.get_session() as s:
            row = Member(id=uid, guild_id=gid, **kwargs)
            query = s.insert.rows(row)
            query = query.on_conflict(Member.id, Member.guild_id).update(
                getattr(Member, name) for name in kwargs
            )
            await query.run()
        try:
            self._cache['member'][gid][uid].update(kwargs)
        except KeyError:
            pass

    async def get_member(self, gid, uid):
        try:
            return self._cache['member'].setdefault(gid, {})[uid]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Member).where((Member.id == uid)
                                               & (Member.guild_id == gid))
                member = await query.first()
            if member is None:
                ret = {'guild_id': gid, 'id': uid}
            else:
                ret = to_dict(member)
            self._cache['member'][gid][uid] = ret
            return ret

    async def update_channel(self, gid, cid, **kwargs):
        async with self.db.get_session() as s:
            row = Channel(id=cid, guild_id=gid, **kwargs)
            query = s.insert.rows(row)
            query = query.on_conflict(Channel.id).update(getattr(Channel, name) for name in kwargs)
            await query.run()
        try:
            self._cache['channel'][gid][cid].update(kwargs)
        except KeyError:
            pass

    async def get_channel(self, gid, cid):
        try:
            return self._cache['channel'].setdefault(gid, {})[cid]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Channel).where((Channel.id == cid)
                                                & (Channel.guild_id == gid))
                channel = await query.first()
            if channel is None:
                ret = {'guild_id': gid, 'id': cid}
            else:
                ret = to_dict(channel)
            self._cache['channel'][gid][cid] = ret
            return ret
