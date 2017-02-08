import asyncio
import json
import os
import sqlite3

import aiohttp
from discord.ext import commands

import to_sqlalchemy


class EDDB:
    def __init__(self, bot):
        self.bot = bot
        self.updating = False
        with open('config.json') as file:
            self.hash = json.load(file).get('eddb_hash', None)

    @commands.group(aliases=['elite', 'ed'])
    async def eddb(self, ctx):
        """Commands for getting data from EDDB.io"""
        if ctx.invoked_subcommand is None:
            await ctx.send('Invalid command passed. Try "{self.bot.command_prefix[0]}help eddb"')
        
    @eddb.command(aliases=['sys'])
    async def system(self, ctx, *, inp):
        """Searches the database for a system."""

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, system_search, inp)

        await ctx.send(result)

    @eddb.command(aliases=['sta'])
    async def station(self, ctx, *, inp):
        """Searches the database for a station.
            To specify the system, put a comma after the station name and put the system there."""

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, station_search, inp)

        await ctx.send(result)

    @eddb.command(aliases=['b', 'bod'])
    async def body(self, ctx, *, inp):
        """Searches the database for a stellar body."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, body_search, inp)

        await ctx.send(result)

    @eddb.command(aliases=['u', 'upd'])
    async def update(self, ctx, force: bool=False):
        """Updates the database. Will take some time."""
        if not self.updating:
            self.updating = True
            await ctx.send('Database update in progress...')
            print('Checking whether an ed.db update is necessary.')
            session = aiohttp.ClientSession()
            hashfile = 'systems_recently.csv'
            async with session.get(f'https://eddb.io/archive/v5/{hashfile}') as resp:
                with open(hashfile, 'wb') as handle:
                    async for chunk in resp.content.iter_chunked(1024):
                        handle.write(chunk)
            session.close()
            with open(hashfile) as file:
                update_hash = hash(file)
            os.remove(hashfile)         
            if update_hash == self.hash and not force:
                await ctx.send('Update not necessary.')
                self.updating = False
                return
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, to_sqlalchemy.update)
            
            self.hash = update_hash
            with open('config.json') as file:
                data = json.load(file)
            data.update({'eddb_hash': self.hash})
            with open('config.json', 'w') as file:
                json.dump(data, file)
            self.updating = False
            await ctx.send('Database update complete.')
        else:
            await ctx.send('Database update still in progress.')

    @update.error
    async def update_error(self, exception, ctx):
        await self.bot.handle_error(exception, ctx)

    @eddb.command(aliases=['c', 'com', 'comm'])
    async def commodity(self, ctx, *, inp):
        """Searches the database for information on a commodity. Specify the station to get listing data.

            Input in the format: commodity[, station[, system]]"""
        loop = asyncio.get_event_loop()
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

    if target_system is not None:
        target_system = target_system.lower()
        table = conn.execute('select id from populated where lower(name)=?', (target_system,))
        results = table.fetchone()
        if results:
            target_system = results[0]
            query += " and system_id = ?"
        else:
            return 'System not found.'

    args = (search,)
    if target_system:
        args += (target_system,)

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
    search = search.lower().split(', ')
    conn = sqlite3.connect('data/ed.db').cursor()

    if len(search) == 1:
        table = conn.execute('select * from commodities where lower(name)=?', (search[0],))
        result = table.fetchone()
        if result:
            keys = tuple(i[0] for i in table.description)
            return '\n'.join(f'{key.replace("_", " ").title()}: {val}' for key, val in zip(keys[1:], result[1:]))

    elif len(search) < 4:
        table = conn.execute('select id from commodities where lower(name)=?', (search[0],))
        result = table.fetchone()
        if not result:
            return 'Commodity not found.'
        commodity_id = result[0]

        query = 'select id from stations where lower(name)=?'
        args = (search[1],)

        if len(search) == 3:
            table = conn.execute('select id from systems where lower(name)=?', (search[2],))
            result = table.fetchone()
            if not result:
                return 'System not found.'
            system_id = result[0]
            query += ' and system_id=?'
            args += (system_id,)
        table = conn.execute(query, args)
        result = table.fetchall()
        if not result:
            return 'Station not found.'
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
    from os import path
    if not path.exists('./data/ed.db'):
        from to_sqlalchemy import update
        future = bot.loop.run_in_executor(None, update, ())
        bot.loop.create_task(future)
    bot.add_cog(EDDB(bot))
