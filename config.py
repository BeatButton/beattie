from schema.config import Table, Guild, Member, Channel
from utils.asyncqlio import to_dict


class Config:
    def __init__(self, bot):
        self.db = bot.db
        self.db.bind_tables(Table)
        self._cache = {}
        self._cache['member'] = {}
        self._cache['channel'] = {}

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
            await s.remove(Member).where(Member.guild_id == gid)
            await s.remove(Channel).where(Channel.guild_id == gid)
        self._cache.pop(gid, None)
        self._cache['member'].pop(gid, None)
        self._cache['channel'].pop(gid, None)

    async def update_member(self, gid, uid, **kwargs):
        async with self.db.get_session() as s:
            query = s.select(Member).where((Member.id == uid)
                                           & (Member.guild_id == gid))
            member = await query.first()
            if member is None:
                await s.add(Member(id=uid, guild_id=gid, **kwargs))
                cache_dict = {'guild_id': gid, 'id': uid}
                cache_dict.update(kwargs)
                self._cache['member'].setdefault(gid, {})[uid] = cache_dict
            else:
                for attr, value in kwargs.items():
                    setattr(member, attr, value)
                await s.merge(member)
                cache = self._cache['member']
                cache.setdefault(gid, {})[uid] = to_dict(member)

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
            query = s.select(Channel).where((Channel.id == cid)
                                            & (Channel.guild_id == gid))
            channel = await query.first()
            if channel is None:
                await s.add(Channel(id=cid, guild_id=gid, **kwargs))
                cache_dict = {'guild_id': gid, 'id': cid}
                cache_dict.update(kwargs)
                self._cache['channel'].setdefault(gid, {})[cid] = cache_dict
            else:
                for attr, value in kwargs.items():
                    setattr(channel, attr, value)
                await s.merge(channel)
                cache = self._cache['channel']
                cache.setdefault(gid, {})[cid] = to_dict(channel)

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
