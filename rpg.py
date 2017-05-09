import asyncio
from concurrent import futures
import os
import random
import re
from urllib.parse import parse_qs

import discord
from discord.ext import commands
from lxml import etree

from starwars import starroller, die_names


class RPG:
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def choose(self, ctx, *options):
        """Choose between some options. Use quotes if they have spaces."""
        await ctx.send(random.choice(options))

    @commands.command()
    async def tarot(self, ctx):
        async with ctx.typing():
            cards = os.listdir('data/tarot')
            card = random.choice(cards)
            match = re.match(r'[IVX_]*([\w_]+)\.jpg', card)
            name = match.groups()[0].replace('_', ' ')
            embed = discord.Embed()
            embed.title = name
            filename = card.replace('_', '')
            embed.set_image(url=f'attachment://{filename}')
            await ctx.send(file=discord.File(f'data/tarot/{card}', filename),
                           embed=embed)

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
        You can join rolls with commas
        """
        if inp == 'stats':
            inp = '4d6v1x6t'
        inp = ''.join(inp.split()).lower()
        expr = r'^([\d]*d?\d+([+\-^v]\d+)?(x\d+)?([ts]{1,2})?,?)+(?<!,)$'
        if re.match(expr, inp) is None:
            raise commands.BadArgument

        rolls = inp.split(',')
        args_batch = []
        for roll in rolls:
            if 'd' not in roll:
                roll = f'1d{roll}'
            elif roll[0] == 'd':
                roll = f'1{roll}'
            args = tuple(int(arg) for arg in re.findall(r'\d+', roll))

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
            args_batch.append(args)

        future = loop.run_in_executor(None, self.roll_helper, args_batch)
        async with ctx.typing():
            results = await asyncio.wait_for(future, 10, loop=loop)

        out = []
        for roll, result in zip(rolls, results):
            total = 't' in roll
            if total:
                result = [[sum(roll_)] for roll_ in result]
            if 's' in inp:
                for roll_ in result:
                    roll_.sort()
                result.sort()
            if total or len(result) == 1:
                result = [roll_[0] for roll_ in result]
            if times == 1:
                result = result[0]
            out.append(f'{roll}: {result}')
        await ctx.reply('\n'.join(out))

    def roll_helper(self, rolls):
        out = []
        for roll in rolls:
            out.append(roller(*roll))
        return out

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
    async def shadowroll_error(self, e, ctx):
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
        expr = r'^(\d+[a-z])+$'
        match = re.match(expr, inp)
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


def roller(num=1, sides=20, lo_drop=0, hi_drop=0, mod=0, times=1):
    rolls = []
    for _ in range(times):
        pool = [random.randint(1, sides) for _ in range(num)]
        if lo_drop or hi_drop:
            sorted_pool = sorted(pool)
            dropped_vals = sorted_pool[:lo_drop] + sorted_pool[num-hi_drop:]
            for val in dropped_vals:
                pool.remove(val)
        if mod:
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
    if count1 < rolls / 2:
        result = f'{hits} hit{s}.'
    elif hits == 0:
        result = 'Critical glitch.'
    else:
        result = f'Glitch with {hits} hit{s}.'

    return result


def setup(bot):
    bot.add_cog(RPG(bot))
