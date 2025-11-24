from __future__ import annotations

import asyncio
import os
import random
import re
from concurrent import futures
from itertools import islice
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from discord.ext.commands import Cog

from beattie.utils.converters import SUITS, SuitConverter
from beattie.utils.genesys import die_names, genesysroller

if TYPE_CHECKING:
    from collections.abc import Collection

    from beattie.bot import BeattieBot
    from beattie.context import BContext

RollArg = tuple[int, int, int, int, int, int]
L2 = list[int]
L1 = list[L2]

ROLL_EXPR = re.compile(
    r"^(?:(?P<num>\d*)d)?(?P<sides>\d+)(?:[+-](?P<mod>\d+))?"
    r"(?:[v^](?P<drop>\d+))?(?:x(?P<times>\d+))?(?:[ts]{1,2})?$",
)
SHADOWRUN_EXPR = re.compile(r"^\d+e?$")
GENESYS_ROLL_EXPR = re.compile(r"^(?:\d+[a-z])+$")
GENESYS_DIE_EXPR = re.compile(r"\d+[a-z]")

TAROT_EXPR = re.compile(r"(?:\w+/)+[IVX0_]*([\w_]+)\.jpg")
TAROT_URL = "https://www.trustedtarot.com/cards/{}/"


class RPG(Cog):
    @commands.command()
    async def choose(self, ctx: BContext, *options: str):
        """Choose between some options. Use quotes if they have spaces."""
        match options:
            case []:
                await ctx.send("Choose nothing? Is this some sort of metaphor?")
            case [_]:
                await ctx.send("That's not much of a choice!")
            case _:
                choice = random.choice(options)
                await ctx.send(f"I choose {choice}.")

    @commands.command()
    async def tarot(
        self,
        ctx: BContext,
        *,
        suits: Collection[str] = commands.param(
            converter=SuitConverter,
            default=SUITS,
            displayed_default="",
        ),
    ):
        """Get a random tarot card.

        You can specify the suits from which to pull, options are:
        minor:
            cups
            swords
            wands
            pentacles
        major"""
        cards = []
        for root, _dirs, files in islice(os.walk("data/tarot"), 1, None):
            if root.rpartition("/")[2] in suits:
                cards += [f"{root}/{card}" for card in files]
        card = random.choice(cards).replace("\\", "/")
        match = TAROT_EXPR.match(card)
        assert match is not None
        name = match.groups()[0].replace("_", " ")
        url = TAROT_URL.format(name.lower().replace(" ", "-"))
        embed = discord.Embed()
        embed.title = name
        embed.url = url
        filename = card.rpartition("/")[2]
        embed.set_image(url=f"attachment://{filename}")
        await ctx.send(file=discord.File(f"{card}"), embed=embed)

    @commands.command()
    async def sooth(
        self,
        ctx: BContext,
    ):
        """Get a random sooth card."""
        cards = os.listdir("data/sooth")
        card = random.choice(cards)
        embed = discord.Embed()
        embed.title = card.rpartition(".")[0]
        embed.set_image(url=f"attachment://{card}")
        await ctx.send(file=discord.File(f"data/sooth/{card}"), embed=embed)

    @commands.command(aliases=["r"])
    async def roll(self, ctx: BContext, *, roll: str = "1d20"):
        """Roll some dice!

        Can roll multiple dice of any size, with modifiers.
        Format: XdY([^v]Z)([+-]W)(xN)(s)(t)
        X is the number of dice
        Y is the number of sides
        ^ drops the Z highest dice
        v drops the Z lowest dice
        + adds W to the result
        - subtracts W from the result
        x repeats the roll N times
        s sorts the results
        t totals each roll
        """
        if roll == "stats":
            roll = "4d6v1x6t"
        roll = "".join(roll.split()).lower()

        if (match := ROLL_EXPR.match(roll)) is None:
            raise commands.BadArgument

        args: dict[str, int] = {
            k: int(v) if v else 0 for k, v in match.groupdict().items()
        }

        num = args["num"] or 1

        if (sides := args["sides"]) == 0:
            raise commands.BadArgument

        hi_drop = 0
        lo_drop = 0

        if (mod := args["mod"]) and "-" in roll:
            mod = -mod

        if drop := args["drop"]:
            if drop >= num:
                raise commands.BadArgument
            if "^" in roll:
                hi_drop = drop
            else:
                lo_drop = drop

        times = args["times"] or 1

        roller_args = (num, sides, lo_drop, hi_drop, mod, times)

        future = asyncio.to_thread(roller, *roller_args)
        async with ctx.typing():
            result = await asyncio.wait_for(future, 10)

        if "d" not in roll:
            roll = f"1d{roll}"
        elif roll[0] == "d":
            roll = f"1{roll}"

        total = "t" in roll

        if total:
            result = [[sum(roll_)] for roll_ in result]

        if "s" in roll:
            for roll_ in result:
                roll_.sort()
            result.sort()

        out = denest(result)
        await ctx.reply(f"{roll}: {out}")

    @roll.error
    async def roll_error(self, ctx: BContext, e: Exception):
        if isinstance(e, commands.CommandInvokeError):
            e = e.original
        if isinstance(e, (commands.MissingRequiredArgument, commands.BadArgument)):
            await ctx.send(
                "Invalid input. Valid input examples:"
                "\n1d20+3"
                "\n1d6"
                "\n2d8-4"
                "\n2d20+2v1"
                "\n4d6v1x6t",
            )
        elif isinstance(e, asyncio.TimeoutError):
            await ctx.reply("Your execution took too long. Roll fewer dice.")
        elif isinstance(e, discord.HTTPException):
            await ctx.reply("Your results were too long. Maybe sum them?")
        else:
            await ctx.bot.handle_error(ctx, e)

    @commands.command(aliases=["shadroll", "sr"])
    async def shadowroll(self, ctx: BContext, *, inp: str):
        """Roll some dice - for Shadowrun!

        Format: N[e]
        Roll N six-sided dice and return the number of dice that rolled 5 or 6.
        If you put "e" after the number, 6s are counted and then rerolled."""
        inp = inp.strip()
        if not SHADOWRUN_EXPR.match(inp):
            raise commands.BadArgument

        edge = "e" in inp
        num = int(inp.rstrip("e"))

        future = asyncio.to_thread(shadowroller, num, edge=edge)
        async with ctx.typing():
            result = await asyncio.wait_for(future, 10)

        await ctx.reply(result)

    @shadowroll.error
    async def shadowroll_error(self, ctx: BContext, e: Exception):
        if isinstance(e, commands.CommandInvokeError):
            e = e.original
        if isinstance(e, (commands.MissingRequiredArgument, commands.BadArgument)):
            await ctx.send("Invalid input. Valid input examples:\n6\n13e")
        elif isinstance(e, futures.TimeoutError):
            await ctx.reply("Your execution took too long. Roll fewer dice.")
        else:
            await ctx.bot.handle_error(ctx, e)

    @commands.command(aliases=["gr"])
    async def genesysroll(self, ctx: BContext, *, inp: str):
        """Roll some dice - for Fantasy Flight Genesys!

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

        if (match := GENESYS_ROLL_EXPR.match(inp)) is None:
            raise commands.BadArgument
        matches = GENESYS_DIE_EXPR.finditer(inp)
        dice = {}
        for match in matches:
            roll = match.group(0)
            num = int(roll[:-1])
            die_code = roll[-1]
            try:
                die = die_names[die_code]
            except KeyError:
                await ctx.send(f'Die "{die_code}" does not exist.')
                return
            dice[die] = num

        future = asyncio.to_thread(genesysroller, **dice)
        async with ctx.typing():
            try:
                result = await asyncio.wait_for(future, 10)
            except ValueError:
                await ctx.send("Force dice cannot be used with other dice.")
            else:
                await ctx.reply(str(result))

    @genesysroll.error
    async def genesysroll_error(self, ctx: BContext, e: Exception):
        if isinstance(e, commands.CommandInvokeError):
            e = e.original
        if isinstance(e, futures.TimeoutError):
            await ctx.reply("Your execution took too long. Roll fewer dice.")
        else:
            await ctx.bot.handle_error(ctx, e)

    @commands.command(aliases=["coin", "coinflip"])
    async def flip(self, ctx: BContext):
        result = random.choice(("Heads", "Tails"))
        await ctx.send(f"{result}!")


def roller(
    num: int = 1,
    sides: int = 20,
    lo_drop: int = 0,
    hi_drop: int = 0,
    mod: int = 0,
    times: int = 1,
) -> list[list[int]]:
    rolls = []
    for _ in range(times):
        pool = [random.randint(1, sides) for _ in range(num)]
        if lo_drop or hi_drop:
            sorted_pool = sorted(pool)
            dropped_vals = sorted_pool[:lo_drop] + sorted_pool[num - hi_drop :]
            for val in dropped_vals:
                pool.remove(val)
        if mod:
            pool = [sum(pool) + mod]
        rolls.append(pool)
    return rolls


def shadowroller(num: int, *, edge: bool = False) -> str:
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
    s = "s" if hits != 1 else ""
    if count1 < rolls / 2:
        result = f"{hits} hit{s}."
    elif hits == 0:
        result = "Critical glitch."
    else:
        result = f"Glitch with {hits} hit{s}."

    return result


def denest(rolls: L1) -> str:
    # this isn't my fault
    rolls2: L1 | L2 = [roll[0] for roll in rolls] if len(rolls[0]) == 1 else rolls
    rolls3: L1 | L2 | int = rolls2[0] if len(rolls2) == 1 else rolls2

    return str(rolls3)


async def setup(bot: BeattieBot):
    await bot.add_cog(RPG())
