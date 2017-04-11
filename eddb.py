import json
import time

import asyncpg
from aitertools import anext
from discord.ext import commands
import yaml

from utils.aioutils import areader, make_batches
from utils.contextmanagers import tmp_dl


class EDDB:
    def __init__(self, bot):
        self.bot = bot
        self.updating = False
        self.batch_size = 10_000
        self.url = 'https://eddb.io/archive/v5/'
        self.bot.loop.create_task(self._connect())
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.password = data.get('eddb_password', '')

    async def _connect(self):
        self.conn = await asyncpg.connect(user='postgres',
                                          password=self.password,
                                          database='ed.db', host='localhost')

    @commands.group(aliases=['elite', 'ed'])
    async def eddb(self, ctx):
        """Commands for getting data from EDDB.io"""
        if ctx.invoked_subcommand is None:
            await ctx.send('Invalid command passed. '
                           f'Try "{ctx.prefix}help eddb"')

    @eddb.command(aliases=['sys'])
    async def system(self, ctx, *, search):
        """Searches the database for a system."""
        search = search.lower()
        output = ''
        conn = self.conn
        async with ctx.typing():
            query = 'SELECT * FROM systems_populated WHERE LOWER(name) = $1'
            system = await conn.fetchrow(query, search)
            if system:
                system = dict(system.items())
                system['population'] = f'{system["population"]:,d}'
                del system['id']
                output = '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                   for key, val in system.items() if val)
            else:
                output = f'No system {search} found.'
        await ctx.send(output)

    @eddb.command(aliases=['sta'])
    async def station(self, ctx, *, search):
        """Searches the database for a station.
           Optionally, specify a system.

           Input in the format: station[, system]"""
        search = search.lower()
        output = ''
        target_system = None
        conn = self.conn
        async with ctx.typing():
            if ',' in search:
                search, target_system = (i.strip() for i in search.split(','))

            query = 'SELECT * FROM stations WHERE LOWER(name) = $1'
            args = (search,)

            if target_system:
                target_system = target_system.lower()
                system = await conn.fetchrow('SELECT id FROM systems_populated'
                                             ' WHERE LOWER(name) = $1',
                                             target_system)

                if system:
                    query += " AND system_id = $2"
                    args += (system['id'],)
                else:
                    await ctx.send(f'No system {target_system} found.')
                    return

            stations = await conn.fetch(query, *args)

            if len(stations) == 1:
                station = dict(stations[0].items())
                del station['id']
                del station['system_id']
                output = '\n'.join(f'{key.replace("_", " ").title()}: {val}'
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
        conn = self.conn
        async with ctx.typing():
            if len(search) == 1:
                query = 'SELECT * FROM commodities WHERE LOWER(name) = $1'
                commodity = await conn.fetchrow(query, search[0])
                if commodity:
                    output = '\n'.join(f'{k.replace("_", " ").title()}: {v}'
                                       for k, v in commodity.items())
                else:
                    output = f'Commodity {search[0]} not found.'

            elif len(search) < 4:
                query = 'SELECT id FROM commodities WHERE LOWER(name) = $1'
                commodity = await conn.fetchrow(query, search[0])
                if not commodity:
                    await ctx.send(f'Commodity {search[0]} not found.')
                    return

                commodity_id = commodity['id']
                query = 'SELECT id FROM stations WHERE LOWER(name) = $1'
                args = (search[1],)

                if len(search) == 3:
                    system_query = ('SELECT id FROM systems_populated '
                                    'WHERE LOWER(name) = $1')
                    system = await conn.fetchrow(system_query, search[2])
                    if not system:
                        await ctx.send(f'System {search[2]} not found.')
                        return
                    query += ' AND system_id = $2'
                    args += (system['id'],)

                listings = await conn.fetch(query, *args)

                if not listings:
                    await ctx.send(f'Station {search[1]} not found.')
                    return
                elif len(listings) > 1:
                    await ctx.send(f'Multiple stations called {search[1]} '
                                   'found, please specify system.')
                    return

                station_id = listings[0]['id']
                query = ('SELECT * FROM listings WHERE station_id = $1 '
                         'AND commodity_id = $2')
                args = (station_id, commodity_id)
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
    async def update(self, ctx, force: bool=False):
        """Updates the database. Will take some time."""
        if self.updating:
            await ctx.send('Database update still in progress.')
            return
        self.updating = True
        await ctx.send('Database update in progress...')
        with open('config/eddb_schema.json') as file:
            schema = json.load(file)

        for name in schema:
            self.bot.logger.info(f'Downloading {name}')
            async with tmp_dl(self.bot.session, f'{self.url}{name}') as file:
                self.bot.logger.info(f'Creating table for {name}')
                await self.make_table(file, f'tmp/{name}', schema[name])

        self.updating = False
        self.bot.logger.info('ed.db update complete')
        await ctx.send('Database update complete.')

    @update.error
    async def update_error(self, exception, ctx):
        self.updating = False
        await self.bot.handle_error(exception, ctx)

    async def make_table(self, file, path, cols, encoding='utf8'):
        file_ext = path.rpartition('.')[-1]
        table_name = path.rpartition('/')[-1].partition('.')[0]
        if file_ext == 'csv':
            file = self.csv_formatter(file)
        elif file_ext == 'jsonl':
            file = self.multi_json(file)
        elif file_ext == 'json':
            file = self.single_json(file)
        else:
            raise ValueError
        query = (f'DROP TABLE IF EXISTS {table_name};'
                 f'CREATE TABLE {table_name}('
                 f'{",".join(f"{k} {v}" for k,v in cols.items())}'
                 ', PRIMARY KEY(id));')
        await self.conn.execute(query)
        interp_string = ','.join(f'${n+1}'
                                 for n, _ in enumerate(cols))
        query = (f'INSERT INTO {table_name} VALUES('
                 f'{interp_string});')
        async for batch in make_batches(file, self.batch_size):
            values = []
            async for row in file:
                row = {col: row[col] for col in cols}
                for col, val in row.items():
                    if val is None:
                        row[col] = val = ''
                    type_ = cols[col]
                    if type_ == 'bool':
                        row[col] = bool(val)
                    elif 'int' in type_:
                        try:
                            row[col] = int(val)
                        except ValueError:
                            row[col] = 0
                    elif type_ == 'real':
                        try:
                            row[col] = float(val)
                        except ValueError:
                            row[col] = 0.0
                    elif isinstance(val, list):
                        row[col] = ', '.join(val)
                    elif isinstance(val, dict):
                        row[col] = next(v for k, v in val.items()
                                        if k != 'id')
                values.append(tuple(row.values()))
            await self.conn.executemany(query, values)

    async def csv_formatter(self, file):
        file = areader(file)
        header = await anext(file)
        async for line in file:
            yield dict(zip(header, line))

    async def single_json(self, file):
        text = await file.read()
        data = json.loads(text)
        while data:
            yield data.pop(0)

    async def multi_json(self, file):
        async for line in file:
            yield json.loads(line)


def setup(bot):
    bot.add_cog(EDDB(bot))
