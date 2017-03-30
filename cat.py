import io

import aiohttp
from discord.ext import commands
import yaml


class Cat:
    def __init__(self, bot):
        self.bot = bot
        with open('config.yaml') as file:
            data = yaml.load(file)
        self.key = data.get('cat_key', '')
        self.url = 'http://thecatapi.com/api/images/get'
        self.params = {'api_key': self.key,
                       'type': 'png,jpg'}

    @commands.command()
    async def cat(self, ctx):
        session = self.bot.session
        async with ctx.typing(), session.get(self.url, self.params) as resp:
            image = io.BytesIO(await resp.content.read())
            ext = resp.headers['Content-Type'].partition('/')[2]
        await ctx.send(file=image, filename=f'{ctx.message.id}.{ext}')


def setup(bot):
    bot.add_cog(Cat(bot))
