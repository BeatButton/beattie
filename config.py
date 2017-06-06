from schema.config import Table, Guild
from utils.asyncqlio import to_dict


class Config:
    def __init__(self, bot):
        self.db = bot.db
        self.db.bind_tables(Table)

    async def get(self, gid):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
        return {k: v for k, v in to_dict(guild).items() if v}

    async def set(self, gid, **kwargs):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            for attr, value in kwargs.items():
                setattr(guild, attr, value)
            await s.merge(guild)

    async def add(self, gid, **kwargs):
        async with self.db.get_session() as s:
            await s.add(Guild(id=gid, **kwargs))

    async def remove(self, gid):
        query = f'DELETE FROM guild WHERE id = {gid};'
        async with self.db.get_session() as s:
            await s.execute(query, {})
