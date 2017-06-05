import asyncpg
import yaml


class Config:
    def __init__(self, bot):
        self.pool = bot.pool

    async def get(self, gid):
        query = 'SELECT * FROM guild WHERE id = $1;'
        args = (gid,)
        async with self.pool.acquire() as conn:
            guild = await conn.fetchrow(query, *args)
        return {k: v for k, v in guild.items() if v}

    async def set(self, gid, **kwargs):
        fmt = ', '.join(f'{k} = ${i}' for i, k in enumerate(kwargs, 2))
        query = f'UPDATE guild SET {fmt} WHERE id = $1;'
        args = (gid, *kwargs.values())
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

    async def add(self, gid, **kwargs):
        kwargs['id'] = gid
        keys = ', '.join(kwargs)
        fmt = ', '.join(f'{k} = ${i}' for i, k in enumerate(kwargs))
        query = f'INSERT INTO guild ({keys}) VALUES ({fmt});'
        async with self.pool.acquire() as conn:
            await conn.execute(query, *kwargs.values())

    async def remove(self, gid):
        query = 'DELETE FROM guild WHERE id = $1;'
        args = (gid,)
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)
