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

    def __del__(self):
        self.bot.loop.create_task(self.db.close())

    async def get(self, gid):
        async with self.pool.acquire() as conn:
            query = 'SELECT * FROM guild WHERE id = $1;'
            args = (gid,)
            guild = conn.fetchrow(query, args)
            return dict(guild.items())

    async def set(self, gid, **kwargs):
        async with self.pool.acquire() as conn:
            fmt = ', '.join(f'{k} = ${i}' for i, k in enumerate(kwargs, 2))
            query = f'UPDATE guild SET {fmt} WHERE id = $1;'
            args = (gid, *kwargs.values())
            await conn.execute(query, args)

    async def add(self, gid, **kwargs):
        async with self.conn.acquire() as conn:
            kwargs['id'] = gid
            fmt = ', '.join(f'{k} = ${i}' for i, k in enumerate(kwargs))
            query = f'INSERT INTO guild VALUES ({fmt});'
            await conn.execute(query, *kwargs.values())

    async def remove(self, gid):
        async with self.db.get_session() as s:
            query = 'DELETE FROM guild WHERE id = $1;'
            args = (gid,)
            await s.execute(query, args)
