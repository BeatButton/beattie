import json
import os
import logging
import time

import aiofiles
import aiohttp
import aiopg
from discord.ext import commands

from utils import checks


class EDDB:
    def __init__(self, bot):
        self.bot = bot
        self.updating = False
        self.pool = None
        self.urlbase = 'https://eddb.io/archive/v5/'
        with open('config.json') as file:
            self.hash = json.load(file).get('eddb_hash', None)


    async def tmp_download(self, file):
        async with aiofiles.open(f'tmp/{file}', 'wb') as handle, \
                    self.bot.session.get(f'{self.urlbase}{file}') as resp:
            async for block in resp.content.iter_chunked(1024):
                await handle.write(block)

    async def _create_pool(self):
        self.pool = await aiopg.create_pool('dbname=ed.db user=postgres password=passwd host=127.0.0.1')

    @commands.group(aliases=['elite', 'ed'])
    async def eddb(self, ctx):
        """Commands for getting data from EDDB.io"""
        if ctx.invoked_subcommand is None:
            await ctx.send(f'Invalid command passed. Try "{ctx.prefix}help eddb"')
        
    @eddb.command(aliases=['sys'])
    async def system(self, ctx, *, search):
        """Searches the database for a system."""
        search = search.lower()
        result = ''
        async with self.pool.acquire() as conn, conn.cursor() as cur, ctx.typing():
            table = await cur.execute('SELECT * FROM populated WHERE LOWER(name) = $1', (search,))
            results = await table.fetchone()
            if not results:
                await cur.execute('SELECT * FROM systems WHERE LOWER(name) = $1', (search,))
                results = await cur.fetchone()
            if results:
                keys = tuple(i[0] for i in table.description)
                result = '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[1:], results[1:]) if val)
            else:
                result = 'No systems found.'                
        await ctx.send(result)

    @eddb.command(aliases=['sta'])
    async def station(self, ctx, *, search):
        """Searches the database for a station.
            To specify the system, put a comma after the station name and put the system there."""
        search = search.lower()
        result = ''
        async with self.pool.acquire() as conn, conn.cursor() as cur, ctx.typing():
            if ',' in search:
                search, target_system = (i.strip() for i in search.split(','))

            query = 'SELECT * FROM stations WHERE LOWER(name) = $1'
            args = (search,)
            
            if target_system:
                target_system = target_system.lower()
                await cur.execute('SELECT id FROM populated WHERE LOWER(name) = $1', (target_system,))
                results = await cur.fetchone()
                if results:
                    args += (results[0],)
                    query += " AND system_id = $2"
                else:
                     await ctx.send('System not found.')
                     return
                    
            await cur.execute(query, args)
            results = await cur.fetchall()

            if len(results) == 1:
                keys = tuple(i[0] for i in result.description)
                results = results[0]
                result = '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[2:], results[2:]) if val)
            elif not results:
                result =  'Station not found.'
            else:
                result = 'Multiple stations found, please specify system.'

            await ctx.send(result)


    @eddb.command(aliases=['c', 'com', 'comm'])
    async def commodity(self, ctx, *, search):
        """Searches the database for information on a commodity. Specify the station to get listing data.

            Input in the format: commodity[, station[, system]]"""
        search = [term.strip() for term in search.lower().split(',')]
        result = ''
        async with self.pool.acquire() as conn, conn.cursor() as cur, ctx.typing():
            if len(search) == 1:
                await cur.execute('SELECT * FROM commodities WHERE LOWER(name) = $1', (search[0],))
                results = await table.fetchone()
                if result:
                    keys = tuple(i[0] for i in table.description)
                    result = '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[1:], results[1:]))
                else:
                    result = 'Commodity not found.'

            elif len(search) < 4:
                await cur.execute('SELECT id FROM commodities WHER LOWER(name) = $1', (search[0],))
                results = await cur.fetchone()
                if not results:
                    await ctx.send('Commodity not found.')
                    return

                commodity_id = results[0]
                query = 'SELECT id FROM STATIONS WHERE LOWER(name) = $1'
                args = (search[1],)

                if len(search) == 3:
                    await cur.execute('SELECT * FROM populated WHERE LOWER(name) = $1', (search[2],))
                    resulst = await cur.fetchone()
                    if not results:
                        await ctx.send('System not found.')
                        return
                    system_id = result[0]
                    query += ' AND system_id=?'
                    args += (system_id,)
                    
                await cur.execute(query, args)
                results = await cur.fetchall()
                
                if not results:
                    await ctx.send("System not populated or station doesn't exist.")
                    return 
                elif len(results) > 1:
                    await ctx.send('Multiple stations found, please specify system.')
                    return

                station_id = result[0][0]
                await cur.execute('SELECT * FROM listings WHERE station_id=? '
                                     'AND commodity_id=?', (station_id, commodity_id))
                results = await table.fetchone()
                if not results:
                    await ctx.send('Commodity not available to be bought or sold at station.')
                    return

                keys = (i[0] for i in table.description)
                results = {k: v for k, v in zip(keys, results)}
                del results['station_id']
                del results['commodity_id']
                del results['id']
                result = f'Commodity: {search[0].title()}\n'
                if len(search) > 1:
                    result += f'Station: {search[1].title()}\n'
                if len(search) > 2:
                    result += f'System: {search[2].title()}\n'
                result = ('\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in results.items()))

            else:
                result = 'Too many commas. What does that even mean.'
            
        await ctx.send(result)

    @eddb.command(aliases=['b'])
    async def body(self, ctx, *, search):
        search = search.lower()
        result = ''
        async with self.pool.acquire() as conn, conn.cursor() as cur, ctx.typing():
            await cur.execute('select * from bodies where lower(name) = ?', (search,))
            results = await cur.fetchone()
            if results:
                keys = tuple(i[0] for i in result.description)
                result = '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[2:], results[2:]) if val)
            else:
                result = 'No bodies found.'

        await ctx.send(result)

    @eddb.command(aliases=['u', 'upd'])
    @checks.is_owner()
    async def update(self, ctx, force: bool=False):
        """Updates the database. Will take some time."""
        if self.updating:
            await ctx.send('Database update still in progress.')
            return
        self.updating = True
        batch_size = 10_000 - 1
        await ctx.send('Database update in progress...')
        '''self.bot.logger.log(logging.DEBUG, 'Checking whether an ed.db update is necessary.')

        hashfile = 'systems_recently.csv'

        if not os.path.isdir('tmp'):
            os.mkdir('tmp')

        await self.tmp_download(hashfile)

        async with aiofiles.open(f'tmp/{hashfile}') as file:
            update_hash = hash(file)
            
        os.remove(f'tmp/{hashfile}')
        
        if update_hash == self.hash and not force:
            await ctx.send('Update not necessary.')
            self.updating = False
            return
        
        self.bot.logger.log(logging.INFO, 'Updating ed.db')

        '''

        self.bot.logger.log(logging.DEBUG, 'Beginning database creation.')

        '''await self.tmp_download('commodities.json')
        
        self.bot.logger.log(logging.DEBUG, 'commodities.json downloaded.')
        
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            count = 0
            commit = ''
            await cur.execute('DROP TABLE IF EXISTS commodities;'
                              'CREATE TABLE commodities('
                              'id int,'
                              'name text,'
                              'average_price int,'
                              'is_rare bool,'
                              'category text,'
                              'PRIMARY KEY(id));')
            with open('tmp/commodities.json', encoding='utf-8') as file:
                commodities = json.load(file)
            for commodity in commodities:
                del commodity['category_id']
                commodity['category'] = commodity['category']['name']
                commodity['is_rare'] = bool(commodity['is_rare'])
                keys, vals = zip(*commodity.items())
                new_vals = []
                keys = map(str, keys)
                for val in vals:
                    if isinstance(val, list):
                        val = ', '.join(val)
                    if isinstance(val, str):
                        val = val.replace("'", "''")
                        val = f"'{val}'"
                    new_vals.append(str(val))
                vals = new_vals
                commit += (f'INSERT INTO commodities ({", ".join(keys)})'
                                  f'VALUES ({", ".join(vals)});')
                count += 1
                if count > batch_size:
                    await cur.execute(commit)
                    count = 0
                    commit = ''
            await cur.execute(commit)

        self.bot.logger.log(logging.DEBUG, 'Table commodities created.')

        os.remove('tmp/commodities.json')

        await self.tmp_download('systems_populated.jsonl')

        self.bot.logger.log(logging.DEBUG, 'File systems_populated.jsonl downloaded.')
        
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            counter = 0
            commit = ''
            await cur.execute('DROP TABLE IF EXISTS populated;'
                              'CREATE TABLE populated('
                              'id int,'
                              'name text,'
                              'population bigint,'
                              'government text,'
                              'allegiance text,'
                              'state text,'
                              'security text,'
                              'power text,'
                              'PRIMARY KEY(id));')
            async with aiofiles.open('tmp/systems_populated.jsonl', encoding='utf-8') as populated:
                props = ('id', 'name', 'population', 'government', 'allegiance', 'state', 'security', 'power')
                async for system in populated:
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
                    count += 1
                    if count > batch_size:
                        await cur.execute(commit)
                        count = 0
                        commit = ''
            await cur.execute(commit)

        self.bot.logger.log(logging.DEBUG, 'Table populated created.')

        os.remove('tmp/systems_populated.jsonl')

        await self.tmp_download('stations.jsonl')

        self.bot.logger.log(logging.DEBUG, 'File stations.jsonl downloaded.')
        
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            count = 0
            commit = ''
            await cur.execute('DROP TABLE IF EXISTS stations;'
                              'CREATE TABLE stations('
                              'id int,'
                              'system_id int,'
                              'name text,'
                              'max_landing_pad_size char(1),'
                              'distance_to_star int,'
                              'government text,'
                              'allegiance text,'
                              'state text,'
                              'type text,'
                              'has_blackmarket bool,'
                              'has_commodities bool,'
                              'import_commodities text,'
                              'export_commodities text,'
                              'prohibited_commodities text,'
                              'economies text,'
                              'is_planetary bool,'
                              'selling_ships text,'
                              'PRIMARY KEY(id));')
            async with aiofiles.open('tmp/stations.jsonl', encoding='utf-8') as stations:
                props = ('id', 'system_id', 'name', 'max_landing_pad_size', 'distance_to_star', 'government',
                         'allegiance', 'state', 'type', 'has_blackmarket', 'has_commodities',
                         'import_commodities', 'export_commodities', 'prohibited_commodities',
                         'economies', 'is_planetary', 'selling_ships')
                async for station in stations:
                    station = json.loads(station)
                    station = {prop: station[prop] for prop in props}
                    if station['distance_to_star'] is None:
                        station['distance_to_star'] = 0
                    if station['max_landing_pad_size'] is None or len(station['max_landing_pad_size']) > 1:
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
                    commit += (f'INSERT INTO stations ({", ".join(keys)})'
                                      f'VALUES ({", ".join(vals)});')
                    count += 1
                    if count > batch_size:
                        await cur.execute(commit)
                        count = 0
                        commit = ''
            await cur.execute(commit)

        self.bot.logger.log(logging.DEBUG, 'Table stations created.')

        os.remove('tmp/stations.jsonl')

        await self.tmp_download('listings.csv')

        self.bot.logger.log(logging.DEBUG, 'File listings.csv downloaded.')

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            count = 0
            commit = ''
            await cur.execute('DROP TABLE IF EXISTS listings;'
                              'CREATE TABLE listings('
                              'id int,'
                              'station_id int,'
                              'commodity_id int,'
                              'supply int,'
                              'buy_price int,'
                              'sell_price int,'
                              'demand int,'
                              'collected_at text,'
                              'PRIMARY KEY(id));')
                              
            async with aiofiles.open('tmp/listings.csv', encoding='utf-8') as listings:
                listings = csv_reader(listings)
                header = await listings.__anext__()
                props = {prop: header.index(prop) for prop in header}
                timestamp = props['collected_at']
                async for listing in listings:
                    listing[timestamp] = f'{time.ctime(int(listing[timestamp]))}'
                    keys, vals = zip(*((prop, listing[index]) for prop, index in props.items()))
                    vals = list(vals)
                    for i, val in enumerate(vals):
                        if not val.isdigit():
                            vals[i] = f"'{val}'"
                    commit += (f'INSERT INTO listings ({", ".join(keys)})'
                                      f'VALUES ({", ".join(vals)});')
                    count += 1
                    if count > batch_size:
                        await cur.execute(commit)
                        count = 0
                        commit = ''
            await cur.execute(commit)

        self.bot.logger.log(logging.DEBUG, 'Table listings created.')

        os.remove('tmp/listings.csv')

        await self.tmp_download('systems.csv')

        self.bot.logger.log(logging.DEBUG, 'File systems.csv downloaded.')'''

        async with self.pool.acquire() as conn, conn.cursor() as cur:
            count = 0
            commit = ''
            await cur.execute('DROP TABLE IF EXISTS systems;'
                              'CREATE TABLE systems('
                              'id int,'
                              'name text,'
                              'population bigint,'
                              'government text,'
                              'allegiance text,'
                              'state text,'
                              'security text,'
                              'power text,'
                              'PRIMARY KEY(id));')
            async with aiofiles.open('tmp/systems.csv', encoding='utf-8') as systems:
                systems = csv_reader(systems)
                header = await systems.__anext__()
                props = {prop: header.index(prop) for prop in
                         ('id', 'name', 'population', 'government', 'allegiance', 'state', 'security', 'power')}
                async for system in systems:
                    try:
                        int(system[props['population']])
                    except ValueError:
                        system[props['population']] = '0'
                    keys, vals = zip(*((prop, system[index]) for prop, index in props.items()))
                    vals = list(vals)
                    for i, val in enumerate(vals):
                        if not val.isdigit():
                            val = val.replace("'", "''")
                            vals[i] = f"'{val}'"
                    commit += (f'INSERT INTO systems ({", ".join(keys)})'
                                      f'VALUES ({", ".join(vals)});')
                    count += 1
                    if count > batch_size:
                        await cur.execute(commit)
                        count = 0
                        commit = ''
                await cur.execute(commit)

        self.bot.logger.log(logging.DEBUG, 'Table systems created.')

        os.remove('tmp/systems.csv')

        await self.tmp_download('bodies.jsonl')

        self.bot.logger.log(logging.DEBUG, 'File bodies.jsonl downloaded.')
        
        async with self.pool.acquire() as conn, conn.cursor() as cur:
            count = 0
            commit = ''
            await cur.execute('DROP TABLE IF EXISTS bodies;'
                              'CREATE TABLE bodies('
                              'id int,'
                              'system_id int,'
                              'name text,'
                              'group text,'
                              'type text,'
                              'atmosphere_type text,'
                              'solar_masses real,'
                              'solar_radius real,'
                              'earth_masses real,'
                              'radius int,'
                              'gravity real,'
                              'surface_pressure real,'
                              'volcanism_type,'
                              'is_rotational_period_tidally_locked bool,'
                              'is_landable bool,'
                              'PRIMARY KEY(id));')
            async with aiofiles.open('tmp/bodies.jsonl', encoding='utf-8') as bodies:
                props = ('id', 'system_id', 'name', 'group', 'type', 'atmosphere_type', 'solar_masses',  'solar_radius',
                         'earth_masses', 'radius', 'gravity', 'surface_pressure', 'volcanism_type',
                         'is_rotational_period_tidally_locked', 'is_landable')
                async for body in bodies:
                    body = json.loads(body)
                    for key in body.keys():
                        if key.endswith('_name'):
                            body[key.replace('_name', '')] = body.pop(key)
                    vals = [body[prop] for prop in props]
                    keys = props
                    new_vals = []
                    for val in vals:
                        if val is None:
                            val = ''
                        if isinstance(val, list):
                            val =', '.join(val)
                        if isinstance(val, str):
                            val = val.replace("'", "''")
                            val = f"'{val}'"
                        new_vals.append(str(val))
                    vals = new_vals
                    commit += (f'INSERT INTO bodies ({", ".join(keys)})'
                                      f'VALUES ({", ".join(vals)});')
                    count += 1
                    if count > batch_size:
                        await cur.execute(commit)
                        count = 0
                        commit = ''
            await cur.execute(commit)

        self.bot.logger.log(logging.DEBUG, 'Table bodies created.')

        os.remove('tmp/bodies.jsonl')

        try:
            os.rmdir('tmp')
        except PermissionError:
            self.bot.logger.log(logging.WARNING, 'Failed to delete tmp directory.')

        self.bot.logger.log(logging.INFO, 'ed.db update complete.')
        
        self.hash = update_hash
        async with aio.open('config.json') as file:
            data = json.load(file)
        data.update({'eddb_hash': self.hash})
        async with aiofiles.open('config.json', 'w') as file:
            json.dump(data, file)
        self.updating = False
        await ctx.send('Database update complete.')

    @update.error
    async def update_error(self, exception, ctx):
        self.updating = False
        await self.bot.handle_error(exception, ctx)


async def csv_reader(aiofile):
    async for line in aiofile:
        yield [val.strip() for val in line.split(',')]



def setup(bot):
    bot.add_cog(EDDB(bot))
    cog = bot.get_cog('EDDB')
    bot.loop.create_task(cog._create_pool())
    
