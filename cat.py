import io

import aiohttp
from discord.ext import commands
from lxml import etree
import yaml


class Cat:
    def __init__(self, bot):
        self.bot = bot
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.key = data.get('cat_key', '')
        self.url = 'http://thecatapi.com/api/images/get'
        self.params = {'api_key': self.key,
                       'type': 'png,jpg',
                       'format': 'xml',
                       }

    @commands.command()
    async def cat(self, ctx):
        """Gets a picture of a random cat from thecatapi.com!"""
        session = self.bot.session
        async with ctx.typing():
            async with session.get(self.url, params=self.params) as resp:
                if resp.status != 200:
                    await ctx.send(f'Failed with code {resp.status}')
                    return
                root = etree.fromstring(await resp.text())
            url = root.find('.//url').text
            if not url.startswith('http://'):
                url = f'http://{url}'
            filename = url.rpartition('/')[-1]
            async with session.get(url) as resp:
                if resp.status != 200:
                    await ctx.send(f'Failed with code {resp.status}')
                    return
                image = io.BytesIO(await resp.content.read())
        await ctx.send(file=image, filename=filename)

    @cat.error
    async def cat_error(self, e, ctx):
        e = getattr(e, 'original', e)
        if isinstance(e, aiohttp.ServerDisconnectedError):
            await ctx.invoke(self.cat)
        else:
            raise e


def setup(bot):
    bot.add_cog(Cat(bot))
