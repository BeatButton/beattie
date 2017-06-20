from schema.config import Table, Guild
from utils.asyncqlio import to_dict


class Config:
    def __init__(self, bot):
        self.db = bot.db
        self.db.bind_tables(Table)
        self._cache = {}

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
                res = {k: v for k, v in to_dict(guild).items() if v}
            self._cache[gid] = res
            return res

    async def set(self, gid, **kwargs):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            for attr, value in kwargs.items():
                setattr(guild, attr, value)
            await s.merge(guild)
        self._cache[gid] = {k: v for k, v in to_dict(guild).items() if v}

    async def add(self, gid, **kwargs):
        async with self.db.get_session() as s:
            await s.add(Guild(id=gid, **kwargs))

    async def remove(self, gid):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            await s.remove(guild)
        self._cache.pop(gid, None)
