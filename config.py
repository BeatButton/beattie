import asyncpg
import yaml


class Config:
    def __init__(self, bot):
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.password = data.get('config_password', '')
        self.bot = bot
        self.bot.loop.create_task(self._create_pool())

    async def _create_pool(self):
        self.pool = await asyncpg.create_pool(user='beattie',
                                              password=self.password,
                                              database='config',
                                              host='localhost')

    async def get(self, gid):
        query = 'SELECT * FROM guild WHERE id = $1;'
        args = (gid,)
        async with self.pool.acquire() as conn:
            guild = await conn.fetchrow(query, *args)
        return dict(guild.items())

    async def set(self, gid, **kwargs):
        fmt = ', '.join(f'{k} = ${i}' for i, k in enumerate(kwargs, 2))
        query = f'UPDATE guild SET {fmt} WHERE id = $1;'
        args = (gid, *kwargs.values())
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)

    async def add(self, gid, **kwargs):
        kwargs['id'] = gid
        fmt = ', '.join(f'{k} = ${i}' for i, k in enumerate(kwargs))
        query = f'INSERT INTO guild VALUES ({fmt});'
        async with self.pool.acquire() as conn:
            await conn.execute(query, *kwargs.values())

    async def remove(self, gid):
        query = 'DELETE FROM guild WHERE id = $1;'
        args = (gid,)
        async with self.pool.acquire() as conn:
            await conn.execute(query, *args)
