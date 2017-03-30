import io

import aiohttp
import discord
from discord.ext import commands
from lxml import etree
import yaml


class Cat:
    def __init__(self, bot):
        self.bot = bot
        with open('config.yaml') as file:
            data = yaml.load(file)
        self.key = data.get('cat_key', '')
        self.url = 'http://thecatapi.com/api/images/get'
        self.params = {'api_key': self.key,
                       'type': 'png,jpg',
                       'format': 'xml',
                       }

    @commands.command()
    async def cat(self, ctx):
        session = self.bot.session
        async with ctx.typing():
            async with session.get(self.url, params=self.params) as resp:
                root = etree.fromstring(await resp.text())
            url = root.find('.//url').text
            embed = discord.Embed()
            embed.set_image(url=url)
        await ctx.send(embed=embed)



def setup(bot):
    bot.add_cog(Cat(bot))
