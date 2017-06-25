from schema.config import Table, Guild, Member
from utils.asyncqlio import to_dict


class Config:
    def __init__(self, bot):
        self.db = bot.db
        self.db.bind_tables(Table)
        self._cache = {}
        self._member_cache = {}

    async def get(self, gid):
        try:
            return self._cache[gid]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Guild).where(Guild.id == gid)
                guild = await query.first()
            if guild is None:
                res = {}
            else:
                res = to_dict(guild)
            self._cache[gid] = res
            return res

    async def set(self, gid, **kwargs):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            if guild is None:
                await s.add(Guild(id=gid, **kwargs))
                cache_dict = {'id': gid}
                cache_dict.update(kwargs)
                self._cache[gid] = cache_dict
            else:
                for attr, value in kwargs.items():
                    setattr(guild, attr, value)
                await s.merge(guild)
                self._cache[gid] = to_dict(guild)

    async def remove(self, gid):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            if guild is not None:
                await s.remove(guild)
            query = s.select(Member).where(Member.guild_id == gid).delete()
            async for record in query:
                await s.remove(record)
        self._cache.pop(gid, None)
        self._member_cache.pop(gid, None)

    async def update_member(self, gid, uid, **kwargs):
        async with self.db.get_session() as s:
            query = s.select(Member).where((Member.id == uid)
                                           & (Member.guild_id == gid))
            member = await query.first()
            if member is None:
                await s.add(Member(id=uid, guild_id=gid, **kwargs))
                cache_dict = {'guild_id': gid, 'id': uid}
                cache_dict.update(kwargs)
                self._member_cache.setdefault(gid, {})[uid] = cache_dict
            else:
                for attr, value in kwargs.items():
                    setattr(member, attr, value)
                await s.merge(member)
                self._member_cache.setdefault(gid, {})[uid] = to_dict(member)

    async def get_member(self, gid, uid):
        try:
            return self._member_cache[gid][uid]
        except KeyError:
            async with self.db.get_session() as s:
                query = s.select(Member).where((Member.id == uid)
                                               & (Member.guild_id == gid))
                member = await query.first()
            if member is None:
                ret = {'guild_id': gid, '_id': uid}
            else:
                ret = to_dict(member)
            self._member_cache.setdefault(gid, {})[uid] = ret
            return ret
