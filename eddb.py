import json
import logging
import time

from aitertools import anext
from discord.ext import commands
from katagawa.kg import Katagawa
import yaml

from eddb_schema import Commodity, System, Station, Listing
from utils.aioutils import areader, make_batches


class EDDB:
    file_to_type = {
        'commodities.json': Commodity,
        'systems_populated.jsonl': System,
        'stations.jsonl': Station,
        'listings.csv': Listing,
    }

    def __init__(self, bot):
        self.updating = False
        self.logger = None
        self.bot = bot
        self.url = 'https://eddb.io/archive/v5/'
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.password = data.get('eddb_password', '')
        dsn = f'postgresql://postgres:{self.password}@localhost/ed.db'
        self.db = Katagawa(dsn)
        self.bot.loop.create_task(self.db.connect())
        self.parsers = {
            'csv': self.csv_formatter,
            'json': self.single_json,
            'jsonl': self.multi_json,
        }

    @commands.group(aliases=['elite', 'ed'])
    async def eddb(self, ctx):
        """Commands for getting data from EDDB.io"""
        if ctx.invoked_subcommand is None:
            await ctx.send('Invalid command passed. '
                           f'Try "{ctx.prefix}help eddb"')

    @eddb.command(aliases=['logging'], hidden=True)
    @commands.is_owner()
    async def log(self, ctx, enable: bool = True):
        if enable:
            logger = logging.getLogger('katagawa')
            logger.setLevel(logging.DEBUG)
            handler = logging.FileHandler(
                filename='katagawa.log', encoding='utf-8', mode='w')
            logger.addHandler(handler)
            self.logger = logger
            await ctx.send('Logging enabled.')
        else:
            self.logger = None
            await ctx.send('Logging disabled.')

    @eddb.command(hidden=True)
    @commands.is_owner()
    async def debug(self, ctx, *, query):
        async with ctx.typing(), self.db.get_session() as s:
            await ctx.send(await s.fetch(query))

    @eddb.command(aliases=['sys'])
    async def system(self, ctx, *, search):
        """Searches the database for a system."""
        search = search.lower()
        output = ''

        async with ctx.typing(), self.db.get_session() as s:
            query = s.select(System).where(System.name.ilike(search))
            system = await query.first()

            if system:
                system = {k.name: v for k, v in system.to_dict().items()}
                system['population'] = f'{system["population"]:,d}'
                del system['id']
                output = '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                   for key, val in system.items() if val)
            else:
                output = f'System {search} not found.'
        await ctx.send(output)

    @eddb.command(aliases=['sta'])
    async def station(self, ctx, *, search):
        """Searches the database for a station.
           Optionally, specify a system.

           Input in the format: station[, system]"""
        search = search.lower()
        output = ''
        target_system = None
        async with ctx.typing(), self.db.get_session() as s:
            if ',' in search:
                search, target_system = (i.strip() for i in search.split(','))

            query = s.select(Station).where(Station.name.ilike(search))

            if target_system:
                sys_query = s.select(System)
                sys_query = sys_query.where(System.name.ilike(target_system))
                system = await sys_query.first()

                if system:
                    query = query.where(Station.system_id == system.id)
                else:
                    await ctx.send(f'No system {target_system} found.')
                    return

            stations = await (await query.all()).flatten()

            if len(stations) == 1:
                station = stations[0].to_dict()
                station = {k.name: v for k, v in station.items()}
                query = s.select(System)
                query = query.where(System.id == station['system_id'])
                system = await query.first()
                del station['id']
                del station['system_id']
                output = f'System: {system.name}\n'
                output += '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                    for key, val in station.items() if val)
            elif not stations:
                output = f'Station {search} not found.'
            else:
                output = (f'Multiple stations called {search} found, '
                          'please specify system.')

            await ctx.send(output)

    @eddb.command(aliases=['c', 'com', 'comm'])
    async def commodity(self, ctx, *, search):
        """Searches the database for information on a commodity
           Specify the station to get listing data.

           Input in the format: commodity[, station[, system]]"""
        search = [term.strip().lower() for term in search.split(',')]
        output = ''
        async with ctx.typing(), self.db.get_session() as s:
            if len(search) == 1:
                query = s.select(Commodity)
                query = query.where(Commodity.name.ilike(search[0]))
                commodity = await query.first()
                if commodity:
                    commodity = commodity.to_dict()
                    commodity = {k.name: v for k, v in commodity.items()}
                    del commodity['id']
                    output = '\n'.join(f'{k.replace("_", " ").title()}: {v}'
                                       for k, v in commodity.items())
                else:
                    output = f'Commodity {search[0]} not found.'

            elif len(search) < 4:
                query = s.select(Commodity)
                query = query.where(Commodity.name.ilike(search[0]))
                commodity = await query.first()
                if not commodity:
                    await ctx.send(f'Commodity {search[0]} not found.')
                    return

                commodity_id = commodity.id
                query = s.select(Station).where(Station.name.ilike(search[1]))
                if len(search) == 3:
                    sys_query = s.select(System)
                    sys_query = sys_query.where(System.name.ilike(search[2]))
                    system = await sys_query.first()
                    if not system:
                        await ctx.send(f'System {search[2]} not found.')
                        return
                    query = query.where(Station.system_id == system.id)

                stations = await (await query.all()).flatten()

                if not stations:
                    await ctx.send(f'Station {search[1]} not found.')
                    return
                elif len(stations) > 1:
                    await ctx.send(f'Multiple stations called {search[1]} '
                                   'found, please specify system.')
                    return
                station_id = stations[0].id
                query = s.select(Listing)
                query = query.where(Listing.station_id == station_id)
                query = query.where(Listing.commodity_id == commodity_id)
                listing = await query.first()
                if not listing:
                    await ctx.send(f'Commodity {search[0]} not available '
                                   'to be bought or sold at station.')
                    return
                listing = listing.to_dict()
                listing = {k.name: v for k, v in listing.items()}
                del listing['id']
                del listing['station_id']
                del listing['commodity_id']
                fetch_time = int(listing['collected_at'])
                listing['collected_at'] = time.ctime(fetch_time)
                output = f'Commodity: {search[0].title()}\n'
                if len(search) > 1:
                    output += f'Station: {search[1].title()}\n'
                    if len(search) > 2:
                        output += f'System: {search[2].title()}\n'
                output = ('\n'.join(f'{key.replace("_", " ").title()}: {val}'
                          for key, val in listing.items()))

            else:
                output = 'Too many commas. What does that even mean.'

        await ctx.send(output)

    @eddb.command(aliases=['u', 'upd'])
    @commands.is_owner()
    async def update(self, ctx):
        """Updates the database. Will take some time."""
        if self.updating:
            await ctx.send('Database update still in progress.')
            return
        self.updating = True
        await ctx.send('Database update in progress...')

        for name, table in self.file_to_type.items():
            self.bot.logger.info(f'Downloading {name}')
            async with self.bot.tmp_dl(f'{self.url}{name}') as file:
                self.bot.logger.info(f'Creating table for {name}')
                self.updating = name
                schema = {col.name: col.type.sql()
                          for col in table.iter_columns()}
                await self.make_table(file, name, schema)

        self.updating = False
        self.bot.logger.info('ed.db update complete')
        await ctx.send('Database update complete.')

    @update.error
    async def update_error(self, exception, ctx):
        self.updating = False
        await self.bot.handle_error(exception, ctx)

    async def make_table(self, file, name, cols):
        file_ext = name.rpartition('.')[-1]
        file = self.parsers[file_ext](file)
        column = self.file_to_type[name]
        table_name = column.__tablename__
        async with self.db.get_session() as s:
            query = (f'DROP TABLE IF EXISTS {table_name};'
                     f'CREATE TABLE {table_name}('
                     f'{",".join(f"{k} {v}" for k, v in cols.items())},'
                     'PRIMARY KEY(id));')
            await s.execute(query, {})
        # postgresql can only have up to 2 ^ 15 paramters. So, this
        batch_size = 2 ** 15 // len(cols) - 1
        async for batch in make_batches(file, batch_size):
            async with self.db.get_session() as s:
                async for row in batch:
                    s.insert(column(**{col: self.coerce(row[col], cols[col])
                                       for col in cols}))

    @staticmethod
    def coerce(value, type_):
        if isinstance(value, dict):
            value = value['name']
        if type_ == 'BOOLEAN':
            return bool(value)
        if type_ in ('INTEGER', 'BIGINT'):
            try:
                return int(value)
            except (ValueError, TypeError):
                return 0
        if type_ == 'REAL':
            try:
                return float(value)
            except (ValueError, TypeError):
                return 0.0
        return value

    @staticmethod
    async def csv_formatter(file):
        file = areader(file)
        header = await anext(file)
        async for line in file:
            yield dict(zip(header, line))

    @staticmethod
    async def single_json(file):
        text = await file.read()
        data = json.loads(text)
        while data:
            yield data.pop(0)

    @staticmethod
    async def multi_json(file):
        async for line in file:
            yield json.loads(line)


def setup(bot):
    bot.add_cog(EDDB(bot))


def teardown(cog):
    cog.bot.loop.create_task(cog.db.close())
