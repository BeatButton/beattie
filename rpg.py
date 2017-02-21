import asyncio
from concurrent import futures
from random import randint
import re
from urllib.parse import parse_qs

import aiohttp
from discord.ext import commands
from lxml import etree

class RPG:
    def __init__(self, bot):
        self.bot = bot

    @commands.command(aliases=['r'])
    async def roll(self, ctx, *, inp='1d20'):
        """Roll some dice!

        Can roll multiple dice of any size, with modifiers, and drop the lowest of a set of dice.
        Format: XdY([+-^v]Z)(xN)(s)(t)
        X is the number of dice
        Y is the number of sides
        + adds Z to the result
        - subtracts Z from the result
        ^ drops the Z highest dice
        v drops the Z lowest dice
        x repeats the roll N times
        s sorts the results
        t totals each roll
        """
        if inp == 'stats':
            inp = '4d6v1x6t'
        inp = ''.join(inp.split()).lower()
        expr = r'^[\d]*d?\d+(?:[+\-^v]\d+)?(?:x\d+)?(?:[ts]{1,2})?$'
        if re.match(expr, inp) is None:
            raise ValueError
        
        if 'd' not in inp:
            inp = f'1d{inp}'
        elif inp[0] == 'd':
            inp = '1{inp}'
        args = tuple(int(arg) for arg in re.findall(r'\d+', inp))

        num = args[0]
        sides = args[1]

        if '^' in inp:
            hi_drop = args[2]
        else:
            hi_drop = 0

        if 'v' in inp:
            lo_drop = args[2]
        else:
            lo_drop = 0

        if '+' in inp:
            mod = args[2]
        elif '-' in inp:
            mod = -args[2]
        else:
            mod = 0

        if 'x' in inp:
            times = args[-1]
        else:
            times = 1

        loop = asyncio.get_event_loop()
        args = (num, sides, lo_drop, hi_drop, mod, times)
        future = loop.run_in_executor(None, roller, *args)
        async with ctx.typing():
            result = await asyncio.wait_for(future, 10, loop=loop)

        total = 't' in inp
        
        if total:
            result = [[sum(roll_)] for roll_ in result]
        if 's' in inp:
            for roll_ in result: roll_.sort()
            result.sort()
        if total or num == 1:
            result = [roll_[0] for roll_ in result]
        if times == 1:
            result = result[0]
                
        await self.bot.reply(ctx, f'{inp}: {result}')

    @roll.error
    async def roll_error(self, exception, ctx):
        if (isinstance(exception, commands.MissingRequiredArgument)
            or isinstance(exception.original, ValueError)):
            await ctx.send('Invalid input. Valid input examples:'
                               '\n1d20+3'
                               '\n1d6'
                               '\n2d8-4'
                               '\n2d20^1'
                               '\n4d6v1x6t')
        elif isinstance(exception.original, futures.TimeoutError):
            await self.bot.reply(ctx, 'Your execution took too long. Roll fewer dice.')
        elif isinstance(exception.original, discord.HTTPException):
            await self.bot.reply(ctx, 'Your results were too big to fit. Maybe sum them?')
        else:
            await self.bot.handle_error(exception, ctx)


    @commands.command(aliases=['shadroll', 'sr'])
    async def shadowroll(self, ctx, *, inp):
        """Roll some dice - for Shadowrun!

        Format: N[e]
        Rolls N six-sided dice and returns the number of dice that rolled 5 or 6.
        If you put "e" after the number, 6s are counted and then rerolled."""
        inp = inp.strip()
        expr = r'^\d+e?$'
        if not re.match(expr, inp):
            raise ValueError
        edge = 'e' in inp
        if edge:
            inp = inp[:-1]
        num = int(inp)

        loop = asyncio.get_event_loop()
        args = (num, edge)
        future = loop.run_in_executor(None, shadowroller, *args)
        async with ctx.typing():
            result = await asyncio.wait_for(future, 10, loop=loop)

        await self.bot.reply(ctx, result)

    @shadowroll.error
    async def shadowroll_error(self, exception, ctx):
        if (isinstance(exception, commands.MissingRequiredArgument)
            or isinstance(exception.original, ValueError)):
            await ctx.send('Invalid input. Valid input examples:'
                               '\n6'
                               '\n13e')
        elif isinstance(exception.original, futures.TimeoutError):
            await self.bot.reply(ctx, 'Your execution took too long. Roll fewer dice.')
        else:
            await self.bot.handle_error(exception, ctx)

    @commands.command()
    async def srd(self, ctx, *, inp):
        """Search the Pathfinder SRD.

        Returns the first three results from d20pfsrd.com on the search query.
        Copied shamelessly with some minimal editing from RoboDanny."""
        params = {'q': inp + ' site:d20pfsrd.com'}
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 6.3; Win64; x64)'
        }
        entries = []
        async with self.bot.session.get('https://google.com/search', params=params, headers=headers) as resp:
            root = etree.fromstring(await resp.text(), etree.HTMLParser())
        search_nodes = root.findall(".//div[@class='g']")
        for node in search_nodes:
            url_node = node.find('.//h3/a')
            if url_node is None:
                continue
            url = url_node.attrib['href']
            if not url.startswith('/url?'):
                continue

            url = parse_qs(url[5:])['q'][0]

            entries.append(url)
        try:
            msg = entries[0]
        except IndexError:
            msg = 'No results found.'
        else:
            if entries[1:3]:
                msg += '\n\nSee also:\n{}'.format('\n'.join(f'<{entry}>' for entry in entries[1:3]))
        
        await ctx.send(msg)


    @srd.error
    async def srd_error(self, exception, ctx):
        if isinstance(exception, commands.MissingRequiredArgument):
            await ctx.send('Please include a search term.')
        else:
            await self.bot.handle_error(exception, ctx)


def roller(num=1, sides=20, lo_drop=0, hi_drop=0, mod=0, times=1):
    rolls = []
    for _ in range(times):
        pool = [randint(1, sides) for _ in range(num)]
        if lo_drop + hi_drop > 0:
            sorted_pool = sorted(pool)
            dropped_vals = sorted_pool[:lo_drop] + sorted_pool[num-hi_drop:]
            for val in dropped_vals:
                pool.remove(val)
        if mod != 0:
            pool = [sum(pool) + mod]
        rolls.append(pool)
    return rolls

def shadowroller(num, edge=False):
    rolls = hits = count1 = 0
    while True:
        count6 = 0
        rolls += num
        for _ in range(num):
            roll = randint(1, 6)
            if roll > 4:
                hits += 1
                if roll == 6:
                    count6 += 1
            elif roll == 1:
                count1 += 1
        if not (count6 > 0 and edge):
            break
        num = count6
    s = 's' if hits != 1 else ''
    if count1 > rolls / 2:
        if hits == 0:
            result = 'Critical glitch.'
        else:
            result = f'Glitch with {hits} hit{s}.'
    else:
        result = f'{hits} hit{s}.'
    return result



def setup(bot):
    bot.add_cog(RPG(bot))

