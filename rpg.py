import asyncio
from concurrent import futures
import random
import re
from urllib.parse import parse_qs

import aiohttp
import discord
from discord.ext import commands
from lxml import etree


class RPG:
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def choose(self, ctx, *options):
        """Choose between some options. Use quotes if they have spaces."""
        await ctx.send(random.choice(options))

    @commands.command(aliases=['r'])
    async def roll(self, ctx, *, inp='1d20'):
        """Roll some dice!

        Can roll multiple dice of any size, with modifiers.
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
            raise commands.BadArgument

        if 'd' not in inp:
            inp = f'1d{inp}'
        elif inp[0] == 'd':
            inp = f'1{inp}'
        args = tuple(int(arg) for arg in re.findall(r'\d+', inp))

        num = args[0]
        sides = args[1]

        hi_drop = 0
        lo_drop = 0
        mod = 0

        if '^' in inp:
            hi_drop = args[2]
        elif 'v' in inp:
            lo_drop = args[2]
        elif '+' in inp:
            mod = args[2]
        elif '-' in inp:
            mod = -args[2]

        if 'x' in inp:
            times = args[-1]
        else:
            times = 1

        loop = self.bot.loop
        args = (num, sides, lo_drop, hi_drop, mod, times)
        future = loop.run_in_executor(None, roller, *args)
        async with ctx.typing():
            result = await asyncio.wait_for(future, 10, loop=loop)

        total = 't' in inp

        if total:
            result = [[sum(roll_)] for roll_ in result]
        if 's' in inp:
            for roll_ in result:
                roll_.sort()
            result.sort()
        if total or num == 1:
            result = [roll_[0] for roll_ in result]
        if times == 1:
            result = result[0]

        await ctx.reply(f'{inp}: {result}')

    @roll.error
    async def roll_error(self, e, ctx):
        e = getattr(e, 'original', e)
        if isinstance(e, (commands.MissingRequiredArgument,
                      commands.BadArgument)):
            await ctx.send('Invalid input. Valid input examples:'
                           '\n1d20+3'
                           '\n1d6'
                           '\n2d8-4'
                           '\n2d20^1'
                           '\n4d6v1x6t')
        elif isinstance(e, futures.TimeoutError):
            await ctx.reply('Your execution took too long. Roll fewer dice.')
        elif isinstance(e, discord.HTTPException):
            await ctx.reply('Your results were too long. Maybe sum them?')
        else:
            await self.bot.handle_error(e, ctx)

    @commands.command(aliases=['shadroll', 'sr'])
    async def shadowroll(self, ctx, *, inp):
        """Roll some dice - for Shadowrun!

        Format: N[e]
        Roll N six-sided dice and return the number of dice that rolled 5 or 6.
        If you put "e" after the number, 6s are counted and then rerolled."""
        inp = inp.strip()
        expr = r'^\d+e?$'
        if not re.match(expr, inp):
            raise commands.BadArgument
        edge = 'e' in inp
        if edge:
            inp = inp[:-1]
        num = int(inp)

        loop = self.bot.loop
        args = (num, edge)
        future = loop.run_in_executor(None, shadowroller, *args)
        async with ctx.typing():
            result = await asyncio.wait_for(future, 10, loop=loop)

        await ctx.reply(result)

    @shadowroll.error
    async def shadowroll_error(self, exception, ctx):
        e = getattr(e, 'original', e)
        if isinstance(e, (commands.MissingRequiredArgument,
                      commands.BadArgument)):
            await ctx.send('Invalid input. Valid input examples:'
                           '\n6'
                           '\n13e')
        elif isinstance(e, futures.TimeoutError):
            await ctx.reply('Your execution took too long. Roll fewer dice.')
        else:
            await self.bot.handle_error(e, ctx)

    @commands.command(aliases=['sw'])
    async def starroll(self, ctx, *, inp):
        """Roll some dice - for Fantasy Flight Star Wars!

        Available dice:
        b[oost]
        a[bility]
        p[roficiency]
        s[etback]
        d[ifficulty]
        c[hallenge]
        f[orce]

        Input examples:
        4a3d
        3a2p1b4d1c
        2f"""
        inp = inp.lower()
        match = re.match(r'^(\d+[a-z])+$', inp)
        if not match:
            raise commands.BadArgument
        dice = {}
        for roll in match.groups():
            num = int(roll[:-1])
            try:
                die = die_names[roll[-1]]
            except KeyError:
                await ctx.send(f'Die "{roll[-1]}" does not exist.')
                return
            dice[die] = num

        loop = self.bot.loop
        future = loop.run_in_executor(None, lambda: starroller(**dice))
        async with ctx.typing():
            try:
                result = await asyncio.wait_for(future, 10, loop=loop)
            except ValueError:
                await ctx.send('Force dice cannot be used with other dice.')
            else:
                await ctx.reply(result)

    @starroll.error
    async def starroll_error(self, e, ctx):
        e = getattr(e, 'original', e)
        if isinstance(e, futures.TimeoutError):
            await ctx.reply('Your execution took too long. Roll fewer dice.')
        else:
            await self.bot.handle_error(e, ctx)

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
        async with ctx.typing():
            async with self.bot.get('https://google.com/search',
                                    params=params, headers=headers) as resp:
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
                    msg += '\n\nSee also:\n{}'.format('\n'.join(f'<{ent}>'
                                                      for ent in entries[1:3]))

        await ctx.send(msg)

    @srd.error
    async def srd_error(self, e, ctx):
        e = getattr(e, 'original', e)
        if isinstance(e, commands.MissingRequiredArgument):
            await ctx.send('Please include a search term.')
        else:
            await self.bot.handle_error(e, ctx)


def roller(num=1, sides=20, lo_drop=0, hi_drop=0, mod=0, times=1):
    rolls = []
    for _ in range(times):
        pool = [random.randint(1, sides) for _ in range(num)]
        if lo_drop or hi_drop:
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
            roll = random.randint(1, 6)
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


class Result:
    def __init__(self, advantages=0, hits=0, triumphs=0):
        self.advantages = advantages
        self.hits = hits
        self.triumphs = triumphs

    def __repr__(self):
        return (f'{type(self).__name__}'
                f'({self.advantages}, {self.hits}, {self.triumphs})')

    def __str__(self):
        ret = []

        if self.hits > 0:
            s = 's' if self.hits > 1 else ''
            ret.append(f'{self.hits} hit{s}')
        elif self.hits < 0:
            misses = -self.hits
            es = 'es' if misses > 1 else ''
            ret.append(f'{misses} miss{es}')

        if self.advantages > 0:
            s = 's' if self.advantages > 1 else ''
            ret.append(f'{self.advantages} advantage{s}')
        elif self.advantages < 0:
            disadvantages = -self.advantages
            s = 's' if disadvantages > 1 else ''
            ret.append(f'{disadvantages} disadvantage{s}')

        if self.triumphs > 0:
            s = 's' if self.triumphs > 1 else ''
            ret.append(f'{self.triumphs} triumph{s}')
        elif self.triumphs < 0:
            despairs = -self.triumphs
            s = 's' if despairs > 1 else ''
            ret.append(f'{despairs} despair{s}')

        if ret:
            ret = ', '.join(ret) + '.'
        else:
            ret = 'Wash.'
        return ret

    def __add__(self, other):
        if isinstance(other, Result):
            return type(self)(self.advantages + other.advantages,
                              self.hits + other.hits,
                              self.triumphs + other.triumphs)
        elif isinstance(other, int):
            return type(self)(self.advantages + other,
                              self.hits + other,
                              self.triumphs + other)
        else:
            return NotImplemented

    __radd__ = __add__

    def __mul__(self, other):
        ret = type(self)(self.advantages * other,
                         self.hits * other,
                         self.triumphs * other)
        return ret

    __rmul__ = __mul__

    def __neg__(self):
        return type(self)(-self.advantages, -self.hits, -self.triumphs)


class Force:
    def __init__(self, light=0, dark=0):
        self.light = light
        self.dark = dark

    def __repr__(self):
        return f'{type(self).__name__}({self.light}, {self.dark})'

    def __str__(self):
        ret = []
        if self.light:
            ret.append(f'{self.light} light side')
        if self.dark:
            ret.append(f'{self.dark} dark side')
        if not ret:
            ret = 'Wash.'
        else:
            ret = ', '.join(ret) + '.'
        return ret

    def __add__(self, other):
        if isinstance(other, Force):
            return type(self)(self.light + other.light,
                              self.dark + other.dark)
        elif isinstance(other, int):
            return type(self)(self.light + other,
                              self.dark + other)
        return NotImplemented

    __radd__ = __add__

    def __mul__(self, other):
        return type(self)(self.light * other, self.dark * other)

    __rmul__ = __mul__


wash = Result()
adv = Result(advantages=1)
hit = Result(hits=1)
triumph = Result(triumphs=1)
dis = -adv
miss = -hit
despair = -triumph
light = Force(light=1)
dark = Force(dark=1)

die_names = {'b': 'boost',
             's': 'setback',
             'a': 'ability',
             'd': 'difficulty',
             'p': 'proficiency',
             'c': 'challenge',
             'f': 'force'}

stardice = {'boost': (wash, wash, hit, hit + adv, 2 * adv, adv),
            'setback': (wash, wash, miss, miss, dis, dis),
            'ability': (wash, hit, hit, 2 * hit, 2 * adv, adv,
                        hit + adv, 2 * adv),
            'difficulty': (wash, miss, 2 * miss, dis, dis, dis,
                           2 * dis, miss + dis),
            'proficiency': (wash, hit, hit, 2 * hit, 2 * hit, adv, hit + adv,
                            hit + adv, hit + adv, adv * 2, adv * 2, triumph),
            'challenge': (wash, miss, miss, 2 * miss, 2 * miss, dis, dis,
                          miss + dis, miss + dis, 2 * dis, 2 * dis, despair),
            'force': (dark, dark, dark, dark, dark, dark, 2 * dark,
                      light, light, 2 * light, 2 * light, 2 * light),
            }


def starroller(**kwargs):
    if 'force' in kwargs:
        if len(kwargs) > 1:
            raise ValueError
        return sum(random.choice(stardice['force'])
                   for _ in range(kwargs['force']))
    result = Result()
    for die in kwargs:
        result += sum(random.choice(stardice[die])
                      for _ in range(kwargs[die]))
    return result


def setup(bot):
    bot.add_cog(RPG(bot))
