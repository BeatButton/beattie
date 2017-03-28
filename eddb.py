import json
import time

import aiopg
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
        self.bot.loop.create_task(self._create_pool())
        with open('config.yaml') as file:
            data = yaml.load(file)
        self.password = data.get('eddb_password', '')

    async def _create_pool(self):
        self.pool = await aiopg.create_pool('dbname=ed.db user=postgres '
                                            f'password={self.password} '
                                            'host=localhost')

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
        typing = ctx.typing
        async with typing(), self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute('SELECT * FROM systems_populated '
                              'WHERE LOWER(name) = (%s)', (search,))
            results = await cur.fetchone()
            if results:
                results = dict(zip((i[0] for i in cur.description), results))
                results['population'] = f'{results["population"]:,d}'
                del results['id']
                output = '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                   for key, val in results.items() if val)
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
        typing = ctx.typing
        async with typing(), self.pool.acquire() as conn, conn.cursor() as cur:
            if ',' in search:
                search, target_system = (i.strip() for i in search.split(','))

            query = 'SELECT * FROM stations WHERE LOWER(name) = (%s)'
            args = (search,)

            if target_system:
                target_system = target_system.lower()
                await cur.execute('SELECT id FROM systems_populated '
                                  'WHERE LOWER(name) = (%s)', (target_system,))
                results = await cur.fetchone()
                if results:
                    args += (results[0],)
                    query += " AND system_id = (%s)"
                else:
                    await ctx.send(f'No system {target_system} found.')
                    return

            await cur.execute(query, args)
            results = await cur.fetchall()

            if len(results) == 1:
                results = dict(zip((i[0] for i in cur.description),
                                   results[0]))
                del results['id']
                del results['system_id']
                output = '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                   for key, val in results.items() if val)
            elif not results:
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
        typing = ctx.typing
        async with typing(), self.pool.acquire() as conn, conn.cursor() as cur:
            if len(search) == 1:
                await cur.execute('SELECT * FROM commodities '
                                  'WHERE LOWER(name) = (%s)', (search[0],))
                results = await cur.fetchone()
                if results:
                    results = dict(zip((i[0] for i in cur.description),
                                       results))
                    output = '\n'.join(f'{k.replace("_", " ").title()}: {v}'
                                       for k, v in results.items())
                else:
                    output = f'Commodity {search[0]} not found.'

            elif len(search) < 4:
                await cur.execute('SELECT id FROM commodities '
                                  'WHERE LOWER(name) = (%s)', (search[0],))
                results = await cur.fetchone()
                if not results:
                    await ctx.send(f'Commodity {search[0]} not found.')
                    return

                commodity_id = results[0]
                query = 'SELECT id FROM stations WHERE LOWER(name) = (%s)'
                args = (search[1],)

                if len(search) == 3:
                    await cur.execute('SELECT * FROM systems_populated '
                                      'WHERE LOWER(name) = (%s)', (search[2],))
                    results = await cur.fetchone()
                    if not results:
                        await ctx.send(f'System {search[2]} not found.')
                        return
                    system_id = results[0]
                    query += ' AND system_id=(%s)'
                    args += (system_id,)

                await cur.execute(query, args)
                results = await cur.fetchall()

                if not results:
                    await ctx.send(f'Station {search[1]} not found.')
                    return
                elif len(results) > 1:
                    await ctx.send(f'Multiple stations called {search[1]} '
                                   'found, please specify system.')
                    return

                station_id = results[0][0]
                await cur.execute('SELECT * FROM listings '
                                  'WHERE station_id=(%s) '
                                  'AND commodity_id=(%s) ',
                                  (station_id, commodity_id))
                results = await cur.fetchone()
                if not results:
                    await ctx.send(f'Commodity {search[0]} not available '
                                   'to be bought or sold at station.')
                    return

                results = dict(zip((i[0] for i in cur.description), results))
                del results['id']
                del results['station_id']
                del results['commodity_id']
                fetch_time = int(results['collected_at'])
                results['collected_at'] = time.ctime(fetch_time)
                output = f'Commodity: {search[0].title()}\n'
                if len(search) > 1:
                    output += f'Station: {search[1].title()}\n'
                if len(search) > 2:
                    output += f'System: {search[2].title()}\n'
                output = ('\n'.join(f'{key.replace("_", " ").title()}: {val}'
                          for key, val in results.items()))

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
        with open('eddb_schema.json') as file:
            schema = json.load(file)

        for name in schema:
            self.bot.logger.info(f'Downloading {name}')
            async with tmp_dl(f'{self.url}{name}', self.bot.session) as file:
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
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute(f'DROP TABLE IF EXISTS {table_name};'
                              f'CREATE TABLE {table_name}('
                              f'{",".join(f"{k} {v}" for k,v in cols.items())}'
                              ', PRIMARY KEY(id));')
            async for batch in make_batches(file, self.batch_size):
                commit = ''
                values = []
                async for row in batch:
                    row = {col: row[col] for col in cols}
                    for col, val in row.items():
                        if val is None:
                            row[col] = val = ''
                        type_ = cols[col]
                        if type_ == 'bool':
                            row[col] = bool(val)
                        elif 'int' in type_:
                            try:
                                int(val)
                            except ValueError:
                                row[col] = 0
                        elif type_ == 'real':
                            try:
                                float(val)
                            except ValueError:
                                row[col] = 0
                        elif isinstance(val, list):
                            row[col] = ', '.join(val)
                        elif isinstance(val, dict):
                            row[col] = next(v for k, v in val.items()
                                            if k != 'id')
                    commit += (f'INSERT INTO {table_name} VALUES('
                               f'{",".join(["%s"] * len(row))});')
                    values.extend(row.values())
                await cur.execute(commit, values, timeout=600)

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
