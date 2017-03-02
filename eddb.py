from functools import partial
import json
import os
import time

import aiofiles
from aiohttp import errors
import aiopg
from aitertools import islice as aislice, chain as achain, aiter, anext
from discord.ext import commands
from psycopg2 import OperationalError
import yaml

from utils import checks
from utils.aioutils import aopen, areader, make_batches


class EDDB:
    def __init__(self, bot):
        self.bot = bot
        self.updating = False
        self.pool = None
        self.urlbase = 'https://eddb.io/archive/v5/'
        self.bot.loop.create_task(self._create_pool())
        with open('config.yaml') as file:
            data = yaml.load(file)
            self.hash = data.get('eddb_hash', None)
            self.password = data.get('eddb_password', '')

    async def tmp_download(self, file, ctx):
        try:
            async with aiofiles.open(f'tmp/{file}', 'wb') as handle,\
               self.bot.session.get(f'{self.urlbase}{file}') as resp:
                async for block in resp.content.iter_chunked(1024):
                    await handle.write(block)
        except (errors.ClientResponseError, errors.ServerDisconnectedError):
            pre = ctx.prefix
            while True:
                await ctx.send(f'Downloading {file} failed. Retry?\n'
                               f'({pre}yes or {pre}no)')
                response = await self.bot.wait_for('message',
                                                   check=lambda m:
                                                   m.content.startswith(pre))
                response = response[len(pre):]
                if response == 'yes':
                    return await self.tmp_download(file, ctx)
                elif response == 'no':
                    return False
        return True

    async def _create_pool(self):
        self.pool = await aiopg.create_pool('dbname=ed.db user=postgres '
                                            f'password={self.password} '
                                            'host=127.0.0.1')

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
            await cur.execute('SELECT * FROM populated '
                              'WHERE LOWER(name) = (%s)', (search,))
            results = await cur.fetchone()
            if results:
                results = list(results)
                pop_index = tuple(i[0]
                                  for i in cur.description).index('population')
                results[pop_index] = f"{results[pop_index]:,d}"
            else:
                await cur.execute('SELECT * FROM system '
                                  'WHERE LOWER(name) = (%s)', (search,),
                                  timeout=600)
                results = await cur.fetchone()
            if results:
                keys = tuple(i[0] for i in cur.description)
                output = '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                   for key, val in zip(keys[1:], results[1:])
                                   if val)
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

            query = 'SELECT * FROM station WHERE LOWER(name) = (%s)'
            args = (search,)

            if target_system:
                target_system = target_system.lower()
                await cur.execute('SELECT id FROM populated '
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
                keys = tuple(i[0] for i in cur.description)
                results = results[0]
                output = '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                   for key, val in zip(keys[2:], results[2:])
                                   if val)
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
                await cur.execute('SELECT * FROM commodity '
                                  'WHERE LOWER(name) = (%s)', (search[0],))
                results = await cur.fetchone()
                if results:
                    keys = tuple(i[0].replace("_", " ")
                                 for i in cur.description)
                    output = '\n'.join(f'{key.title()}: {val}'
                                       for key, val
                                       in zip(keys[1:], results[1:]))
                else:
                    output = f'Commodity {search[0]} not found.'

            elif len(search) < 4:
                await cur.execute('SELECT id FROM commodity '
                                  'WHERE LOWER(name) = (%s)', (search[0],))
                results = await cur.fetchone()
                if not results:
                    await ctx.send(f'Commodity {search[0]} not found.')
                    return

                commodity_id = results[0]
                query = 'SELECT id FROM station WHERE LOWER(name) = (%s)'
                args = (search[1],)

                if len(search) == 3:
                    await cur.execute('SELECT * FROM populated '
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
                await cur.execute('SELECT * FROM listing '
                                  'WHERE station_id=(%s) '
                                  'AND commodity_id=(%s) ',
                                  (station_id, commodity_id))
                results = await cur.fetchone()
                if not results:
                    await ctx.send(f'Commodity {search[0]} not available '
                                   'to be bought or sold at station.')
                    return

                keys = (row[0] for row in cur.description)
                results = {k: v for k, v in zip(keys, results)}
                del results['station_id']
                del results['commodity_id']
                del results['id']
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

    @eddb.command(aliases=['b'])
    async def body(self, ctx, *, search):
        """Searches the database for a stellar body."""
        search = search.lower()
        output = ''
        typing = ctx.typing
        async with self.pool.acquire() as conn, conn.cursor() as cur, typing():
            await cur.execute('SELECT * FROM body '
                              'WHERE LOWER(name) = (%s)', (search,))
            results = await cur.fetchone()
            if results:
                keys = tuple(i[0] for i in cur.description)
                output = '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                   for key, val in zip(keys[2:], results[2:])
                                   if val)
            else:
                output = 'No bodies found.'

        await ctx.send(output)

    @eddb.command(aliases=['u', 'upd'])
    @checks.is_owner()
    async def update(self, ctx, force: bool=False):
        """Updates the database. Will take some time."""
        if self.updating:
            await ctx.send('Database update still in progress.')
            return
        self.updating = True
        batch_size = 1000
        await ctx.send('Database update in progress...')
        self.bot.logger.info('Checking whether an ed.db update is necessary.')

        hashfile = 'systems_recently.csv'

        if not os.path.isdir('tmp'):
            os.mkdir('tmp')

        success = await self.tmp_download(hashfile, ctx)
        if not success:
            return

        with open(f'tmp/{hashfile}') as file:
            update_hash = hash(file)

        os.remove(f'tmp/{hashfile}')

        if update_hash == self.hash and not force:
            await ctx.send('Update not necessary.')
            self.updating = False
            return

        self.bot.logger.info('Updating ed.db')

        await self.tmp_download('commodities.json', ctx)

        self.bot.logger.info('commodities.json downloaded.')

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            commit = ''
            await cur.execute('DROP TABLE IF EXISTS commodity;'
                              'CREATE TABLE commodity('
                              'id int,'
                              'name varchar(32),'
                              'average_price int,'
                              'is_rare bool,'
                              'category varchar(32),'
                              'PRIMARY KEY(id));')
            with open('tmp/commodities.json', encoding='utf-8') as file:
                commodities = json.load(file)
            for commodity in commodities:
                del commodity['category_id']
                commodity['category'] = commodity['category']['name']
                commodity['is_rare'] = bool(commodity['is_rare'])
                keys, vals = zip(*commodity.items())
                vals = list(vals)
                keys = map(str, keys)
                for i, val in enumerate(vals):
                    if isinstance(val, list):
                        vals[i] = val = ', '.join(val)
                    if isinstance(val, str):
                        vals[i] = val = val.replace("'", "''")
                        vals[i] = val = f"'{val}'"
                    vals[i] = str(val)
                commit += (f'INSERT INTO commodity ({", ".join(keys)})'
                           f'VALUES ({", ".join(vals)});')
            await cur.execute(commit)

        self.bot.logger.info('Table commodities created.')

        os.remove('tmp/commodities.json')

        success = await self.tmp_download('systems_populated.jsonl', ctx)
        if not success:
            return

        self.bot.logger.info('File systems_populated.jsonl downloaded.')

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute('DROP TABLE IF EXISTS populated;'
                              'CREATE TABLE populated('
                              'id int,'
                              'name varchar(32),'
                              'population bigint,'
                              'primary_economy text,'
                              'star_type varchar(4),'
                              'bodies text,'
                              'government varchar(16),'
                              'allegiance varchar(16),'
                              'state varchar(16),'
                              'security varchar(8),'
                              'power varchar(32),'
                              'PRIMARY KEY(id));')
            with open('tmp/systems_populated.jsonl') as populated:
                props = ('id', 'name', 'population', 'primary_economy',
                         'government', 'allegiance', 'state', 'security',
                         'power')
                async for batch in make_batches(populated, batch_size):
                    commit = ''
                    async for system in batch:
                        system = json.loads(system)
                        system = {prop: system[prop] for prop in props}
                        if system['population'] is None:
                            system['population'] = 0
                        keys, vals = zip(*system.items())
                        new_vals = []
                        for val in vals:
                            if val is None:
                                val = ''
                            if isinstance(val, list):
                                val = ', '.join(val)
                            if isinstance(val, str):
                                val = val.replace("'", "''")
                                val = f"'{val}'"
                            new_vals.append(str(val))
                        vals = new_vals
                        commit += (f'INSERT INTO populated ({", ".join(keys)})'
                                   f'VALUES ({", ".join(vals)});')
                    await cur.execute(commit)

        self.bot.logger.info('Table populated created.')

        os.remove('tmp/systems_populated.jsonl')

        success = await self.tmp_download('stations.jsonl', ctx)
        if not success:
            return

        self.bot.logger.info('File stations.jsonl downloaded.')

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute('DROP TABLE IF EXISTS station;'
                              'CREATE TABLE station('
                              'id int,'
                              'system_id int,'
                              'name varchar(64),'
                              'max_landing_pad_size char(1),'
                              'distance_to_star int,'
                              'government varchar(16),'
                              'allegiance varchar(16),'
                              'state varchar(16),'
                              'type varchar(32),'
                              'has_blackmarket bool,'
                              'has_commodities bool,'
                              'import_commodities varchar(1024),'
                              'export_commodities varchar(1024),'
                              'prohibited_commodities varchar(512),'
                              'economies varchar(64),'
                              'is_planetary bool,'
                              'selling_ships varchar(512),'
                              'PRIMARY KEY(id));')
            async with aopen('tmp/stations.jsonl') as stations:
                props = ('id', 'system_id', 'name', 'max_landing_pad_size',
                         'distance_to_star', 'government', 'allegiance',
                         'state', 'type', 'has_blackmarket', 'has_commodities',
                         'import_commodities', 'export_commodities',
                         'prohibited_commodities', 'economies', 'is_planetary',
                         'selling_ships')
                async for batch in make_batches(stations, batch_size):
                    commit = ''
                    async for station in batch:
                        station = json.loads(station)
                        station = {prop: station[prop] for prop in props}
                        if station['distance_to_star'] is None:
                            station['distance_to_star'] = 0
                        if (station['max_landing_pad_size'] is None or
                           len(station['max_landing_pad_size']) > 1):
                            station['max_landing_pad_size'] = ''
                        keys, vals = zip(*station.items())
                        new_vals = []
                        for val in vals:
                            if val is None:
                                val = ''
                            if isinstance(val, list):
                                val = ', '.join(val)
                            if isinstance(val, str):
                                val = val.replace("'", "''")
                                val = f"'{val}'"
                            new_vals.append(str(val))
                        vals = new_vals
                        commit += (f'INSERT INTO station ({", ".join(keys)})'
                                   f'VALUES ({", ".join(vals)});')
                    await cur.execute(commit)

        self.bot.logger.info('Table stations created.')

        os.remove('tmp/stations.jsonl')

        success = await self.tmp_download('listings.csv', ctx)
        if not success:
            return

        self.bot.logger.info('File listings.csv downloaded.')

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute('DROP TABLE IF EXISTS listing;'
                              'CREATE TABLE listing('
                              'id int,'
                              'station_id int,'
                              'commodity_id int,'
                              'supply int,'
                              'buy_price int,'
                              'sell_price int,'
                              'demand int,'
                              'collected_at char(24),'
                              'PRIMARY KEY(id));')

            async with aopen('tmp/listings.csv') as listings:
                listings = areader(listings)
                header = await anext(listings)
                props = {prop: header.index(prop) for prop in header}
                timestamp = props['collected_at']
                loop = True
                async for batch in make_batches(listings, batch_size):
                    commit = ''
                    async for listing in batch:
                        listing[timestamp] = (
                            f'{time.ctime(int(listing[timestamp]))}')
                        keys, vals = zip(*((prop, listing[index])
                                         for prop, index in props.items()))
                        vals = list(vals)
                        for i, val in enumerate(vals):
                            if not val.isdigit():
                                vals[i] = f"'{val}'"
                        commit += (f'INSERT INTO listing ({", ".join(keys)})'
                                   f'VALUES ({", ".join(vals)});')
                    await cur.execute(commit)

        self.bot.logger.info('Table listings created.')

        os.remove('tmp/listings.csv')

        success = await self.tmp_download('systems.csv', ctx)
        if not success:
            return

        self.bot.logger.info('File systems.csv downloaded.')

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute('DROP TABLE IF EXISTS system;'
                              'CREATE TABLE system('
                              'id int,'
                              'name varchar(64),'
                              'population bigint,'
                              'star_type varchar(4),'
                              'bodies text,'
                              'government varchar(16),'
                              'allegiance varchar(16),'
                              'state varchar(16),'
                              'security varchar(8),'
                              'power varchar(32),'
                              'PRIMARY KEY(id));')
            async with aopen('tmp/systems.csv') as systems:
                systems = areader(systems)
                header = await anext(systems)
                header += ['star_type', 'bodies']
                props = {prop: header.index(prop) for prop in
                         ('id', 'name', 'population', 'government', 'bodies',
                          'allegiance', 'state', 'security', 'power',
                          'star_type')}
                async for batch in make_batches(systems, batch_size):
                    commit = ''
                    async for system in batch:
                        try:
                            int(system[props['population']])
                        except ValueError:
                            system[props['population']] = '0'
                        system += ['', '']  # star_type and bodies
                        keys, vals = zip(*((prop, system[index])
                                         for prop, index in props.items()))
                        vals = list(vals)
                        for i, val in enumerate(vals):
                            if not val.isdigit():
                                val = val.replace('"', '')
                                val = val.replace("'", "''")
                                vals[i] = f"'{val}'"
                        commit += (f'INSERT INTO system ({", ".join(keys)})'
                                   f'VALUES ({", ".join(vals)});')
                    await cur.execute(commit)

        self.bot.logger.info('Table systems created.')

        os.remove('tmp/systems.csv')

        success = await self.tmp_download('bodies.jsonl', ctx)
        if not success:
            return

        self.bot.logger.info('File bodies.jsonl downloaded.')

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            await cur.execute('DROP TABLE IF EXISTS body;'
                              'CREATE TABLE body('
                              'id int,'
                              'system_id int,'
                              'name varchar(64),'
                              'type varchar(64),'
                              'atmosphere_type varchar(32),'
                              'solar_masses real,'
                              'solar_radius real,'
                              'spectral_class varchar(4),'
                              'earth_masses real,'
                              'radius int,'
                              'rings bool,'
                              'gravity real,'
                              'surface_pressure real,'
                              'volcanism_type varchar(32),'
                              'is_rotational_period_tidally_locked bool,'
                              'is_landable bool,'
                              'PRIMARY KEY(id));')
            async with aopen('tmp/bodies.jsonl') as bodies:
                props = ('id', 'system_id', 'name', 'type', 'atmosphere_type',
                         'solar_masses',  'solar_radius', 'earth_masses',
                         'radius', 'gravity', 'surface_pressure',
                         'volcanism_type',
                         'is_rotational_period_tidally_locked', 'is_landable')
                async for batch in make_batches(bodies, batch_size):
                    commit = ''
                    async for body in batch:
                        body = json.loads(body)
                        for key in ('solar_masses', 'solar_radius', 'rings',
                                    'earth_masses', 'radius', 'gravity',
                                    'surface_pressure', 'spectral_class'):
                            if body[key] is None:
                                body[key] = 0
                        body['is_landable'] = bool(body['is_landable'])
                        body['rings'] = bool(body['rings'])
                        for key in body.keys():
                            if key.endswith('_name'):
                                body[key.replace('_name', '')] = body.pop(key)
                        if body['is_main_star']:
                            commit += ('UPDATE system SET star_type='
                                       f"'{body['spectral_class']}'"
                                       f"WHERE id={body['system_id']};")
                        name = body['name'].replace("'", "''")
                        commit += ('UPDATE system '
                                   f"SET bodies=bodies||'{name}, '"
                                   f"WHERE id={body['system_id']};")
                        vals = [body[prop] for prop in props]
                        keys = props
                        for i, val in enumerate(vals):
                            if val is None:
                                vals[i] = val = ''
                            if isinstance(val, list):
                                vals[i] = val = ', '.join(val)
                            if isinstance(val, str):
                                vals[i] = val = val.replace("'", "''")
                                vals[i] = val = f"'{val}'"
                            vals[i] = str(val)
                        commit += (f'INSERT INTO body ({", ".join(keys)})'
                                   f'VALUES ({", ".join(vals)});')
                    await cur.execute(commit)
                    await cur.execute('UPDATE populated '
                                      'SET bodies=system.bodies '
                                      'FROM system '
                                      'WHERE system.id = populated.id;',
                                      timeout=600)
                    await cur.execute('UPDATE populated '
                                      'SET star_type=system.star_type '
                                      'FROM system '
                                      'WHERE system.id = populated.id;',
                                      timeout=600)

        self.bot.logger.info('Table bodies created.')

        os.remove('tmp/bodies.jsonl')

        try:
            os.rmdir('tmp')
        except OSError:
            self.bot.logger.warning('Failed to delete tmp directory.')

        self.bot.logger.info('ed.db update complete.')

        self.hash = update_hash
        with open('config.yaml') as file:
            data = yaml.load(file)
        data.update({'eddb_hash': self.hash})
        with open('config.yaml', 'w') as file:
            yaml.dump(data, file)
        self.updating = False
        await ctx.send('Database update complete.')

    @update.error
    async def update_error(self, exception, ctx):
        self.updating = False
        await self.bot.handle_error(exception, ctx)


def setup(bot):
    bot.add_cog(EDDB(bot))
