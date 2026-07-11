from __future__ import annotations
import random
from typing import TYPE_CHECKING
import discord
from discord.ext import commands
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext
    
class Gun(Cog):

    def __init__(self):
        with open("data/objects.txt", encoding="utf8") as file:
            self.objects = [line.strip() for line in file.readlines() if line.strip()]
        with open("data/materials.txt", encoding="utf8") as file:
            self.materials = [line.strip() for line in file.readlines() if line.strip()]
        with open("data/quirks.txt", encoding="utf8") as file:
            self.quirks = [line.strip() for line in file.readlines() if line.strip()]
    @commands.command()
    async def gun(self, ctx: BContext):
        await ctx.send("A " + random.choice(self.objects) + 
                       " made of " + random.choice(self.materials) + 
                       " which " + random.choice(self.quirks))

async def setup(bot: BeattieBot):
    await bot.add_cog(Gun())