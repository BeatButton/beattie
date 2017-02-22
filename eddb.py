import asyncio
import csv
import json
import os
import shutil

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
        with open('config.json') as file:
            self.hash = json.load(file).get('eddb_hash', None)

    async def _create_pool(self):
        self.pool = await aiopg.create_pool('dbname=ed.db user=postgres password=passwd host=127.0.0.1')

    @commands.group(aliases=['elite', 'ed'])
    async def eddb(self, ctx):
        """Commands for getting data from EDDB.io"""
        if ctx.invoked_subcommand is None:
            await ctx.send(f'Invalid command passed. Try "{ctx.prefix}help eddb"')
        
    @eddb.command(aliases=['sys'])
    async def system(self, ctx, *, inp):
        """Searches the database for a system."""

        loop = asyncio.get_event_loop()
        async with ctx.typing():
            result = await loop.run_in_executor(None, system_search, inp)
            
        await ctx.send(result)

    @eddb.command(aliases=['sta'])
    async def station(self, ctx, *, inp):
        """Searches the database for a station.
            To specify the system, put a comma after the station name and put the system there."""
        loop = asyncio.get_event_loop()
        async with ctx.typing():
            result = await loop.run_in_executor(None, station_search, inp)
            
        await ctx.send(result)

    @eddb.command(aliases=['b', 'bod'])
    async def body(self, ctx, *, inp):
        """Searches the database for a stellar body."""
        loop = asyncio.get_event_loop()
        async with ctx.typing():
            result = await loop.run_in_executor(None, body_search, inp)

        await ctx.send(result)

    @eddb.command(aliases=['u', 'upd'])
    @checks.is_owner()
    async def update(self, ctx, force: bool=False):
        """Updates the database. Will take some time."""
        if not self.updating:
            self.updating = True
            await ctx.send('Database update in progress...')
            logging.log(logging.DEBUG, 'Checking whether an ed.db update is necessary.')

            hashfile = 'systems_recently.csv'
            urlbase = 'https://eddb.io/archive/v5/'
            async with self.bot.session.get(f'{urlbase}{hashfile}') as resp:
                with open(hashfile, 'wb') as handle:
                    async for chunk in resp.content.iter_chunked(1024):
                        handle.write(chunk)

            async with aiofiles.open(hashfile) as file:
                update_hash = hash(file)
            os.remove(hashfile)         
            if update_hash == self.hash and not force:
                await ctx.send('Update not necessary.')
                self.updating = False
                return
            
            logging.log(logging.INFO, 'Updating ed.db')

            if os.path.isdir('tmp'):
                shutil.rmtree('tmp')
            os.mkdir('tmp')

            logging.log(logging.DEBUG, 'Downloading raw data...')
            files = ('commodities.json', 'systems_populated.jsonl', 'stations.jsonl',
                     'listings.csv', 'systems.csv', 'bodies.jsonl')
            for file in files:
                async with aiofiles.open(f'tmp/{file}', 'wb') as handle:
                    async with self.bot.session.get(f'{urlbase}{file}') as resp:
                        async for block in resp.content.iter_chunked(1024):
                            await handle.write(block)
                logging.log(logging.DEBUG, f'{file} downloaded.')

            logging.log(logging.DEBUG, 'Beginning database creation.')

            async with self.pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute('CREATE TABLE IF_NOT_EXISTS commodities('
                             'id int,'
                             'name text,'
                             'average_price int,'
                             'is_rare bool'
                             'PRIMARY KEY(id));')
                async with aiofiles.open('tmp/commodities.json', encoding='utf-8') as commodities:
                    commodities = json.load(commodities)
                    for commodity in commodities:
                        for k, v in commodity.copy().items():
                            if isinstance(v, list):
                                commodity[k] = ', '.join(v)
                        commodity.pop('category_id')
                        commodity = tuple((k, v) for k, v in commodity.items())
                        await cur.execute(f'INSERT INTO commodities ({", ".join(val[0] for val in commodity)})'
                                          f'VALUES ({", ".join(val[1] for val in commodity)})'
                                          'ON CONFLICT id DO UPDATE SET'
                                          f'{", ".join(f"{val[0]}={val[1]}" for val in commodity)}')

            logging.log(logging.DEBUG, 'Table commodities created.')

            async with self.pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute('CREATE TABLE IF_NOT_EXISTS populated('
                                  'id int,'
                                  'name text,'
                                  'population int,'
                                  'government text,'
                                  'allegiance text,'
                                  'state text,'
                                  'security text',
                                  'power text'
                                  'PRIMARY KEY(id));')
                async with aiofiles.open('tmp/systems_populated.jsonl', encoding='utf-8') as populated:
                    props = ('id', 'name', 'population', 'government', 'allegiance', 'state', 'security', 'power')
                    async for system in populated:
                        system = json.loads(system)
                        for prop in props:
                            if isinstance(system[prop], list):
                                system[prop] = ', '.join(system[prop])
                        system = tuple((prop, system[prop]) for prop in props)
                        await cur.execute(f'INSERT INTO populated ({", ".join(val[0] for val in system)})'
                                          f'VALUES ({", ".join(val[1] for val in system)})'
                                          'ON CONFLICT id DO UPDATE SET'
                                          f'{", ".join(f"{val[0]}={val[1]}" for val in system)}')

            logging.log(logging.DEBUG, 'Table populated created.')
            
            async with self.pool.acquire() as conn, conn.cursor() as cur:
                 await cur.execute('CREATE TABLE IF_NOT_EXISTS stations('
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
                                   'selling_ships text'
                                   'PRIMARY KEY(id));')
                 async with aiofiles.open('tmp/stations.jsonl', encoding='utf-8') as stations:
                    props = ('id', 'system_id', 'name', 'max_landing_pad_size', 'distance_to_star', 'government',
                             'allegiance', 'state', 'type', 'has_blackmarket', 'has_commodities',
                             'import_commodities', 'export_commodities', 'prohibited_commodities',
                             'economies', 'is_planetary', 'selling_ships')
                    async for station in stations:
                        station = json.loads(station)
                        for prop in props:
                            if isinstance(station[prop], list):
                                station[prop] = ', '.join(station[prop])
                        system = tuple((prop, system[prop]) for prop in props)
                        await cur.execute(f'INSERT INTO commodities ({", ".join(val[0] for val in system)})'
                                          f'VALUES ({", ".join(val[1] for val in system)})'
                                          'ON CONFLICT id DO UPDATE SET'
                                          f'{", ".join(f"{val[0]}={val[1]}" for val in system)}')

            logging.log(logging.DEBUG, 'Table stations created.')

            async with self.pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute('CREATE TABLE IF_NOT_EXISTS listings('
                                  'id int,'
                                  'station_id int,'
                                  'commodity_id int,'
                                  'supply int,',
                                  'buy_price int,',
                                  'sell_price int,',
                                  'demand int,',
                                  'collected_at text,'
                                  'PRIMARY KEY(id));')
                                  
                async with aiofiles.open('tmp/listings.csv', encoding='utf-8') as listings:
                    listings = csv.reader(listings)
                    header = next(listings)
                    props = {prop: header.index(prop) for prop in header}
                    timestamp = props['collected_at']
                    for listing in listings:
                        listing[timestamp] = f"'{time.ctime(int(listing[timestamp]))}'"
                        listing = tuple((prop, listing[index]) for prop, index in props.items())
                        for val in listing:
                            if not val[1].isdigit():
                                val[1] = f"'{val[1]}'"
                        await cur.execute(f'INSERT INTO listings ({", ".join(val[0] for val in listing)})'
                                          f'VALUES ({", ".join(val[1] for val in listing)})'
                                          'ON CONFLICT id DO UPDATE SET'
                                          f'{", ".join(f"{val[0]}={val[1]}" for val in listing)}')

            logging.log(logging.DEBUG, 'Table listings created.')

            async with self.pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute('CREATE TABLE IF_NOT_EXISTS populated('
                                  'id int,'
                                  'name text,'
                                  'population int,'
                                  'government text,'
                                  'allegiance text,'
                                  'state text,'
                                  'security text',
                                  'power text'
                                  'PRIMARY KEY(id));')
                async with aiofiles.open('tmp/systems.csv', encoding='utf-8') as systems:
                    systems = csv.reader(systems)
                    header = next(systems)
                    props = {prop: header.index(prop) for prop in
                             ('id', 'name', 'population', 'government', 'allegiance', 'state', 'security', 'power')}
                    for system in systems:
                        system = {prop: system[index] for prop, index in props.items()}
                        for prop in props:
                            if isinstance(system[prop], list):
                                system[prop] = ', '.join(system[prop])
                        system = tuple((prop, system[prop]) for prop in props)
                        for val in system:
                            if not val[1].isdigit():
                                val[1] = f"'{val[1]}'"
                        await cur.execute(f'INSERT INTO systems ({", ".join(val[0] for val in system)})'
                                          f'VALUES ({", ".join(val[1] for val in system)})'
                                          'ON CONFLICT id DO UPDATE SET'
                                          f'{", ".join(f"{val[0]}={val[1]}" for val in system)}')

            logging.log(logging.DEBUG, 'Table systems created.')
            
            async with self.pool.acquire() as conn, conn.cursor() as cur:
                await cur.execute('CREATE TABLE IF_NOT_EXISTS populated('
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
                        for prop in props:
                            if isinstance(body[prop], list):
                                body[prop] = ', '.join(body[prop])
                        await cur.execute(f'INSERT INTO bodies ({", ".join(val[0] for val in body)})'
                                          f'VALUES ({", ".join(val[1] for val in body)})'
                                          'ON CONFLICT id DO UPDATE SET'
                                          f'{", ".join(f"{val[0]}={val[1]}" for val in body)}')

            logging.log(logging.DEBUG, 'Table bodies created.')
            

            logging.log(logging.DEBUG, 'ed.db cleaning up.')
            session.close()
            if not os.path.isdir('data'):
                os.mkdir('data')
            shutil.move('tmp/ed.db', 'data/ed.db')
            shutil.rmtree('tmp')

            logging.log(logging.INFO, 'ed.db update complete.')
            
            self.hash = update_hash
            async with aio.open('config.json') as file:
                data = json.load(file)
            data.update({'eddb_hash': self.hash})
            async with aiofiles.open('config.json', 'w') as file:
                json.dump(data, file)
            self.updating = False
            await ctx.send('Database update complete.')
        else:
            await ctx.send('Database update still in progress.')

    @eddb.command(aliases=['c', 'com', 'comm'])
    async def commodity(self, ctx, *, inp):
        """Searches the database for information on a commodity. Specify the station to get listing data.

            Input in the format: commodity[, station[, system]]"""
        loop = asyncio.get_event_loop()
        async with ctx.typing():
            result = await loop.run_in_executor(None, commodity_search, inp)
            
        await ctx.send(result)


def system_search(search):
    search = search.lower()
    conn = sqlite3.connect('data/ed.db').cursor()
    table = conn.execute('select * from populated where lower(name) = ?', (search,))
    results = table.fetchone()
    if not results:
        table = conn.execute('select * from systems where lower(name) = ?', (search,))
        results = table.fetchone()
    if results:
        keys = tuple(i[0] for i in table.description)
        return '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[1:], results[1:]) if val)
    else:
        return 'No systems found.'


def station_search(search, target_system=None):
    search = search.lower()
    conn = sqlite3.connect('data/ed.db').cursor()
    if ',' in search:
        search, target_system = (i.strip() for i in search.split(','))

    query = 'select * from stations where lower(name) = ?'
    args = (search,)
    
    if target_system:
        target_system = target_system.lower()
        table = conn.execute('select id from populated where lower(name)=?', (target_system,))
        results = table.fetchone()
        if results:
            args += (results[0],)
            query += " and system_id = ?"
        else:
            return 'System not found.'


    result = conn.execute(query, args)
    results = result.fetchall()

    if len(results) == 1:
        keys = tuple(i[0] for i in result.description)
        results = results[0]
        return '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[2:], results[2:]) if val)
    elif not results:
        return 'Station not found.'
    else:
        return 'Multiple stations found, please specify system.'


def commodity_search(search):
    search = [term.strip() for term in search.lower().split(',')]
    conn = sqlite3.connect('data/ed.db').cursor()
    if len(search) == 1:
        table = conn.execute('select * from commodities where lower(name)=?', (search[0],))
        result = table.fetchone()
        if result:
            keys = tuple(i[0] for i in table.description)
            return '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[1:], result[1:]))
        else:
            return 'Commodity not found.'

    elif len(search) < 4:
        table = conn.execute('select id from commodities where lower(name)=?', (search[0],))
        result = table.fetchone()
        if not result:
            return 'Commodity not found.'
        commodity_id = result[0]

        query = 'select id from stations where lower(name)=?'
        args = (search[1],)

        if len(search) == 3:
            table = conn.execute('select * from populated where lower(name) = ?', (search[2],))
            result = table.fetchone()
            if not result:
                return 'System not found.'
            system_id = result[0]
            query += ' and system_id=?'
            args += (system_id,)
        table = conn.execute(query, args)
        result = table.fetchall()
        if not result:
            return "Station not populated or doesn't exist."
        elif len(result) > 1:
            return 'Multiple stations found, please specify system.'
        station_id = result[0][0]

        table = conn.execute('select * from listings where station_id=? '
                             'and commodity_id=?', (station_id, commodity_id))
        result = table.fetchone()
        if not result:
            return 'Commodity not available to be bought or sold at station.'

        keys = (i[0] for i in table.description)
        result = {k: v for k, v in zip(keys, result)}
        result.pop('station_id')
        result.pop('commodity_id')
        result.pop('id')
        ret = f'Commodity: {search[0].title()}\n'
        if len(search) > 1:
            ret += f'Station: {search[1].title()}\n'
        if len(search) > 2:
            ret += f'System: {search[2].title()}\n'
        return ret + ('\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in result.items()))

    else:
        return 'Too many commas. What does that even mean.'


def body_search(search):
    search = search.lower()
    conn = sqlite3.connect('data/ed.db').cursor()
    result = conn.execute('select * from bodies where lower(name) = ?', (search,))
    results = result.fetchone()
    if results:
        keys = tuple(i[0] for i in result.description)
        return '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[2:], results[2:]) if val)
    else:
        return 'No bodies found.'


def setup(bot):
    bot.add_cog(EDDB(bot))
    cog = bot.get_cog('EDDB')
    bot.loop.create_task(cog._create_engine())
    
