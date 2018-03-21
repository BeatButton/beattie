import asyncio
from datetime import datetime
import json
import logging

from aitertools import anext
from discord.ext import commands

from schema.eddb import Table, Commodity, System, Station, Listing
from utils.aioutils import areader, make_batches
from utils.asyncqlio import to_dict


class EDDB:
    file_to_table = {
        'commodities.json': Commodity,
        'systems_populated.jsonl': System,
        'stations.jsonl': Station,
        'listings.csv': Listing,
    }

    def __init__(self, bot):
        self.updating = False
        self.loop = bot.loop
        self.url = 'https://eddb.io/archive/v5/'
        self.db = bot.db
        self.db.bind_tables(Table)
        self.parsers = {
            'csv': self.csv_formatter,
            'json': self.single_json,
            'jsonl': self.multi_json,
        }
        self.logger = bot.logger
        self.get = bot.get

    @commands.group(aliases=['elite', 'ed'])
    async def eddb(self, ctx):
        """Commands for getting data from EDDB.io"""
        if ctx.invoked_subcommand is None:
            await ctx.send('Invalid command passed. '
                           f'Try "{ctx.prefix}help eddb"')

    @eddb.command(hidden=True)
    @commands.is_owner()
    async def debug(self, ctx, *, query):
        async with ctx.typing(), self.db.get_session() as s:
            await ctx.send(await s.fetch(query))

    @eddb.command(hidden=True)
    @commands.is_owner()
    async def log(self, ctx, enabled: bool=True):
        if enabled:
            logger = logging.getLogger('asyncqlio')
            logger.setLevel(logging.DEBUG)
            handler = logging.FileHandler(
                filename='asyncqlio.log', encoding='utf-8', mode='w')
            logger.addHandler(handler)
            await ctx.send('Logging enabled.')
        else:
            self.logger = None
            await ctx.send('Logging disabled.')

    @eddb.command(aliases=['sys'])
    async def system(self, ctx, *, search):
        """Searches the database for a system."""
        async with ctx.typing(), self.db.get_session() as s:
            query = s.select(System).where(System.name.ilike(search))
            system = await query.first()

            if system:
                system = to_dict(system)
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
        if ',' in search:
            search, target_system = (i.strip() for i in search.split(','))

        async with ctx.typing(), self.db.get_session() as s:
            query = s.select(Station).where(Station.name.ilike(search))
            if target_system:
                query = query.where(Station.system.name.ilike(target_system))

            station = await query.first()

            if station:
                system = station.system.name
                station = to_dict(station)
                del station['id']
                del station['system_id']
                output = (f'System: {system}\n'
                          f'Station: {station.pop("name")}\n' +
                          '\n'.join(f'{key.replace("_", " ").title()}: {val}'
                                    for key, val in station.items() if val))
            else:
                output = 'Station not found.'

            await ctx.send(output)

    @eddb.command(aliases=['c', 'com', 'comm'])
    async def commodity(self, ctx, *, search):
        """Searches the database for information on a commodity
           Specify the station to get listing data.

           Input in the format: commodity[, station[, system]]"""
        search = [term.strip() for term in search.split(',')]
        comm, *rest = search + [None, None]
        sta, sys, *_ = rest
        async with ctx.typing(), self.db.get_session() as s:
            if sta is None and sys is None:
                comm = search[0]
                query = s.select(Commodity).where(Commodity.name.ilike(comm))
                commodity = await query.first()
                if commodity:
                    commodity = to_dict(commodity)
                    del commodity['id']
                    output = '\n'.join(f'{k.replace("_", " ").title()}: {v}'
                                       for k, v in commodity.items())
                else:
                    output = 'Commodity not found.'

            else:
                query = s.select(Listing)
                query = query.where(Listing.commodity.name.ilike(comm))
                query = query.where(Listing.station.name.ilike(sta))
                if sys is not None:
                    query = query.where(Listing.station.system.name.ilike(sys))

                listing = await query.first()

                if listing is not None:
                    commodity = listing.commodity.name
                    station = listing.station.name
                    system = listing.station.system.name
                    listing = to_dict(listing)
                    del listing['id']
                    del listing['station_id']
                    del listing['commodity_id']
                    output = (f'Commodity: {commodity}\n'
                              f'Station: {station}\n'
                              f'System: {system}\n' +
                              '\n'.join(f'{k.replace("_", " ").title()}: {v}'
                                        for k, v in listing.items()))
                else:
                    output = 'Commodity not found at station.'

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
        tasks = []
        for name, table in self.file_to_table.items():
            tasks.append(self.loop.create_task(self.update_task(ctx.bot, name, table)))
        for task in tasks:
            await asyncio.wait_for(task, None)
        self.updating = False
        self.logger.info('ed.db update complete')
        await ctx.send('Database update complete.')

    @update.error
    async def update_error(self, ctx, e):
        self.updating = False
        await ctx.bot.handle_error(ctx, e)

    async def update_task(self, bot, name, table):
        self.logger.info(f'Downloading {name}')
        async with self.get(f'{self.url}{name}') as resp:
            self.logger.info(f'Creating table for {name}')
            if name.endswith('.json'):
                file = resp.content
            else:
                file = (line.decode() async for line in resp.content)
            await self.make_table(file, name, table)
            self.logger.info(f'Table {name} created.')
        

    async def make_table(self, file, name, table):
        file_ext = name.rpartition('.')[2]
        file = self.parsers[file_ext](file)
        table_name = table.__tablename__
        cols = {col.name: col.type.sql() for col in table.iter_columns()}
        # postgresql can only have up to 2 ^ 15 paramters. So, this
        batch_size = 2 ** 15 // len(cols) - 1
        await table.drop(cascade=True)
        await table.create()
        async for batch in make_batches(file, batch_size):
            async with self.db.get_session() as s:
                async for row in batch:
                    row = {col: self.coerce(row[col], cols[col])
                           for col in cols}
                    await s.add(table(**row))

    @staticmethod
    def coerce(value, type_):
        if isinstance(value, dict):
            value = value['name']
        if isinstance(value, list):
            value = ', '.join(value)
        if type_ == 'TEXT':
            if not value:
                return ''
            else:
                return str(value)
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
        if type_ == 'BOOLEAN':
            return bool(value)
        if type_ == 'TIMESTAMP':
            return datetime.fromtimestamp(int(value))
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
