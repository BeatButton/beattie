import json
import time

import asyncpg
from aitertools import anext
from discord.ext import commands
import yaml

from utils.aioutils import areader, make_batches


class EDDB:
    file_to_table = {
        'commodities.json': 'commodity',
        'systems_populated.jsonl': 'system',
        'stations.jsonl': 'station',
        'listings.csv': 'listing',
    }

    def __init__(self, bot):
        self.updating = False
        self.bot = bot
        self.url = 'https://eddb.io/archive/v5/'
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.password = data.get('eddb_password', '')

        self.bot.loop.create_task(self._create_pool())
        self.parsers = {
            'csv': self.csv_formatter,
            'json': self.single_json,
            'jsonl': self.multi_json,
        }

    async def _create_pool(self):
        self.pool = await asyncpg.create_pool(user='postgres',
                                              password=self.password,
                                              database='ed.db',
                                              host='localhost')

    @commands.group(aliases=['elite', 'ed'])
    async def eddb(self, ctx):
        """Commands for getting data from EDDB.io"""
        if ctx.invoked_subcommand is None:
            await ctx.send('Invalid command passed. '
                           f'Try "{ctx.prefix}help eddb"')

    @eddb.command(hidden=True)
    @commands.is_owner()
    async def debug(self, ctx, *, query):
        async with ctx.typing(), self.pool.acquire() as conn:
            await ctx.send(await conn.fetch(query))

    @eddb.command(aliases=['sys'])
    async def system(self, ctx, *, search):
        """Searches the database for a system."""
        async with ctx.typing(), self.pool.acquire() as conn:
            query = 'SELECT * from SYSTEM where name ILIKE $1;'
            args = (search,)
            system = await conn.fetchrow(query, *args)

            if system:
                system = dict(system.items())
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
        target_system = None
        async with ctx.typing(), self.pool.acquire() as conn:
            if ',' in search:
                search, target_system = (i.strip() for i in search.split(','))

            query = 'SELECT * FROM station WHERE name ILIKE $1'

            if target_system:
                sys_query = 'SELECT id FROM system WHERE name ILIKE $1;'
                system = await conn.fetchrow(sys_query, target_system)
                if system:
                    query += ' AND system_id = $2'
                    args = (search, dict(system.items())['id'])
                else:
                    await ctx.send(f'No system {target_system} found.')
                    return
            else:
                args = (search,)
            query += ';'
            stations = await conn.fetch(query, *args)

            if len(stations) == 1:
                station = dict(stations[0].items())
                del station['id']
                del station['system_id']
                output = f'System: {target_system}\n'
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
        search = [term.strip() for term in search.split(',')]

        async with ctx.typing(), self.pool.acquire() as conn:
            query = 'SELECT * FROM commodity WHERE name ILIKE $1;'
            args = (search[0],)
            commodity = await conn.fetchrow(query, *args)
            if not commodity:
                await ctx.send(f'Commodity {search[0]} not found.')
                return

            commodity = dict(commodity.items())
            if len(search) == 1:
                del commodity['id']
                output = '\n'.join(f'{k.replace("_", " ").title()}: {v}'
                                   for k, v in commodity.items())

            elif len(search) < 4:
                query = 'SELECT id FROM station WHERE name ILIKE $1'
                if len(search) == 3:
                    sys_query = 'SELECT id FROM system WHERE name ILIKE $1;'
                    system = await conn.fetchrow(sys_query, search[2])
                    if system:
                        query += ' AND system_id = $2'
                        args = (search[1], dict(system.items())['id'])
                    else:
                        await ctx.send(f'No system {search[2]} found.')
                        return
                else:
                    args = (search[1],)
                query += ';'

                stations = await conn.fetch(query, *args)

                if not stations:
                    await ctx.send(f'Station {search[1]} not found.')
                    return
                elif len(stations) > 1:
                    await ctx.send(f'Multiple stations called {search[1]} '
                                   'found, please specify system.')
                    return
                station_id = dict(stations[0].items())['id']
                query = ('SELECT * FROM listing WHERE station_id = $1 '
                         'AND commodity_id = $2;')
                args = (station_id, commodity['id'])
                listing = await conn.fetchrow(query, *args)
                if not listing:
                    await ctx.send(f'Commodity {search[0]} not available '
                                   'to be bought or sold at station.')
                    return
                listing = dict(listing.items())
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

        with open('schema/eddb_schema.json') as file:
            schema = json.load(file)

        for name in schema:
            self.bot.logger.info(f'Downloading {name}')
            async with self.bot.tmp_dl(f'{self.url}{name}') as file:
                self.bot.logger.info(f'Creating table for {name}')
                table_schema = schema[name]
                await self.make_table(file, name, table_schema)

        self.updating = False
        self.bot.logger.info('ed.db update complete')
        await ctx.send('Database update complete.')

    @update.error
    async def update_error(self, ctx, e):
        self.updating = False
        await self.bot.handle_error(ctx, e)

    async def make_table(self, file, name, cols):
        file_ext = name.rpartition('.')[-1]
        file = self.parsers[file_ext](file)
        table_name = self.file_to_table[name]
        # postgresql can only have up to 2 ^ 15 paramters. So, this
        batch_size = 2 ** 15 // len(cols) - 1
        async with self.pool.acquire() as conn:
            query = (f'DROP TABLE IF EXISTS {table_name};'
                     f'CREATE TABLE {table_name}('
                     f'{",".join(f"{k} {v}" for k, v in cols.items())},'
                     'PRIMARY KEY(id));')
            await conn.execute(query)
            fmt = ','.join(['{}'] * len(cols))
            query = f'INSERT INTO {table_name} VALUES({fmt});'
            async for batch in make_batches(file, batch_size):
                commit = ''
                async for row in batch:
                    row = {col: self.coerce(row[col], cols[col])
                           for col in cols}
                    for col, val in row.items():
                        if cols[col] == 'TEXT':
                            val = val.replace("'", "''")
                            val = row[col] = f"'{val}'"
                    commit += query.format(*row.values())
                await conn.execute(commit)

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
        if type_ == 'TEXT':
            if not value:
                return ''
            else:
                return str(value)
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
        # yield from in asynchronous generators when
        for item in data:
            yield item

    @staticmethod
    async def multi_json(file):
        async for line in file:
            yield json.loads(line)


def setup(bot):
    bot.add_cog(EDDB(bot))


def teardown(cog):
    cog.bot.loop.create_task(cog.pool.close())
