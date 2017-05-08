from katagawa.kg import Katagawa

from config_schema import Guild


class Config:
    def __init__(self, bot):
        dsn = f'postgresql://beattie:passwd@localhost/config'
        self.db = Katagawa(dsn)
        self.bot = bot
        self.bot.loop.create_task(self.db.connect())

    def __del__(self):
        self.bot.loop.create_task(self.db.close())

    async def get(self, key, default=None):
        async with self.db.get_session() as s:
            query = s.select(Guild).where(Guild.id == key)
            guild = await query.first()
            if guild:
                return {k.name: v for k, v in guild.to_dict().items()}
            else:
                return default

    async def set(self, **kwargs):
        async with self.db.get_session() as s:
            gid = kwargs['id']
            query = s.select(Guild).where(Guild.id == gid)
            guild = await query.first()
            if guild:
                del kwargs['id']
                values = ','.join(f"{k}='{v}'" for k, v in kwargs.items())
                print(f'update guild set {values} where id = {gid}')
                await s.execute(f'update guild set {values} where id = {gid}')
            else:
                s.insert(Guild(**kwargs))
