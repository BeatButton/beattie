import asyncio
import sqlite3

import discord
from discord.ext import commands

import to_sqlalchemy

class EDDB:
    def __init__(self, bot):
        self.bot = bot
        self.updating = False

    @commands.group(aliases=['elite', 'ed'])
    async def eddb(self, ctx):
        """Commands for getting data from EDDB.io"""
        if ctx.invoked_subcommand is None:
            await self.bot.say(ctx, 'Invalid command passed. '\
                            f'Try "{self.bot.command_prefix[0]}help eddb"')
        
    @eddb.command(aliases=['sys'])
    async def system(self, ctx, *, inp):
        """Searches the database for a system."""

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.system_search, inp)

        await self.bot.say(ctx, result)

    def system_search(self, search):
        search = search.lower()
        conn = sqlite3.connect('data/ed.db').cursor()
        table = conn.execute(f"select * from populated where lower(name) = '{search}'")
        results = table.fetchone()
        if not results:
            table = conn.execute(f"select * from systems where lower(name) = '{search}'")
            results = table.fetchone()
        if results:
            keys = tuple(i[0] for i in table.description) 
            return '\n'.join(f'{key.replace("_", " ").title()}: {field}'
                             for key, field in zip(keys[1:], results[1:]) if field)
        else:
            return 'No systems found.'

    @eddb.command(aliases=['sta'])
    async def station(self, ctx, *, inp):
        """Searches the database for a station.
            To specify the system, put a comma after the station name and put the system there."""

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.station_search, inp)

        await self.bot.say(ctx, result)

    def station_search(self, search, target_system=None, ctx=None):
        search = search.lower()
        conn = sqlite3.connect('data/ed.db').cursor()
        try:
            id_ = int(search)
        except ValueError:
            id_ = -1
        if ',' in search:
            search, target_system = (i.strip() for i in search.split(','))

        query = f"select * from stations where lower(name) = '{search}'"

        if target_system is not None: 
            target_system = target_system.lower()
            table = conn.execute(f"select id from populated where lower(name)='{target_system}'")
            results = table.fetchone()
            if results:
                target_system = results[0]
                query += f" and system_id = {target_system}"
            else:
                return 'System not found.'

        result = conn.execute(query)
        results = result.fetchall()

        if len(results) == 1:
            keys = tuple(i[0] for i in result.description) 
            return '\n'.join(f'{key.replace("_", " ").title()}: {field}'
                             for key, field in zip(keys[2:], results[0][2:]) if field)
        elif not results:
            return 'Station not found.'
        else:
            return 'Multiple stations found, please specify system.'

    @eddb.command(aliases=['b', 'bod'])
    async def body(self, ctx, *, inp):
        """Searches the database for a stellar body."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.body_search, inp)

        await self.bot.say(ctx, result)

    def body_search(self, search):
        search = search.lower()
        conn = sqlite3.connect('data/ed.db').cursor()
        result = conn.execute(f"select * from bodies where lower(name) = '{search}'")
        results = result.fetchone()
        if results:
            keys = tuple(i[0] for i in result.description) 
            return '\n'.join(f'{key.replace("_", " ").title()}: {field}'
                             for key, field in zip(keys[2:], results[2:]) if field)
        else:
            return 'No bodies found.'

    @eddb.command(aliases=['u', 'upd'])
    async def update(self, ctx):
        """Updates the database. Will take some time."""
        if not self.updating:
            self.updating = True
            await self.bot.say(ctx, 'Database update in progress...')
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, to_sqlalchemy.remake)
            await self.bot.say(ctx, 'Database update complete.')
            self.updating = False
        else:
            await self.bot.say(ctx, 'Database update still in progress.')


    @update.error
    async def update_error(self, exception, ctx):
        await self.bot.handle_error(exception, ctx)

    @eddb.command(aliases=['c', 'com', 'comm'])
    async def commodity(self, ctx, *, inp):
        """Searches the database for information on a commodity. Specify the station to get listing data.

            Input in the format: commodity[, station[, system]]"""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self.commodity_search, inp)
        await self.bot.say(ctx, result)


    def commodity_search(self, search):
        search = search.lower().split(', ')
        conn = sqlite3.connect('data/ed.db').cursor()

        if len(search) == 1:
            table = conn.execute(f"select * from commodities where lower(name)='{search[0]}'")
            result = table.fetchone()
            if result:
                keys = tuple(i[0] for i in table.description)
                return '\n'.join(f'{key.replace("_", " ").title()}: {field}'
                                 for key, field in zip(keys[1:], result[1:]))
        
        elif len(search) < 4:
            table = conn.execute(f"select id from commodities where lower(name)='{search[0]}'")
            result = table.fetchone()
            if not result:
                return 'Commodity not found.'
            commodity_id = result[0]

            query = f"select id from stations where lower(name)='{search[1]}'"
            
            if len(search) == 3:
                table = conn.execute(f"select id from systems where lower(name)='{search[2]}'")
                result = table.fetchone()
                if not result:
                    return 'System not found.'
                system_id = result[0]
                query += f" and system_id={system_id}"
            table = conn.execute(query)
            result = table.fetchall()
            if not result:
                return 'Station not found.'
            elif len(result) > 1:
                return 'Multiple stations found, please specify system.'
            station_id = result[0][0]

            table = conn.execute(f"select * from listings where station_id={station_id} "
                                 f"and commodity_id={commodity_id}")
            result = table.fetchone()
            if not result:
                return 'Commodity not available to be bought or sold at station.'

            keys = tuple(i[0] for i in table.description)
            result = {k: v for k, v in zip(keys, result)}
            result.pop('station_id')
            result.pop('commodity_id')
            result.pop('id')
            ret = f'Commodity: {search[0].title()}\n'
            if len(search) > 1:
                ret += f'Station: {search[1].title()}\n'
            if len(search) > 2:
                ret += f'System: {search[2].title()}\n'
            return ret +('\n'.join(f'{key.replace("_", " ").title()}: {field}'
                             for key, field in result.items()))

        else:
            return 'Too many commas. What does that even mean.'
            

def setup(bot):
    from os import path
    if not path.exists('./data/ed.db'):
        from to_sqlalchemy import update
        update()
    bot.add_cog(EDDB(bot))
