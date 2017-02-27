from discord.ext import commands
import json

from lxml import etree

from utils.aioutils import aopen


class Wolfram:
    chars = {0xf74c: ' d',
             0xf74d: 'e',
             0xf74e: 'i',
             0xf74e: 'j',
             0xf7d9: ' = ',
             }

    def __init__(self, bot):
        self.bot = bot
        self.url = 'http://api.wolframalpha.com/v2/query'
        with open('config.json') as file:
            data = json.load(file)
        self.key = data['wolfram_key']

    @commands.command(aliases=['wolf', 'w'])
    async def wolfram(self, ctx, *, inp):
        async with ctx.typing():
            result = await self.search(inp)
        await ctx.send(result)

    async def search(self, inp):
        params = {'input': inp, 'appid': self.key, 'format': 'plaintext'}
        async with self.bot.session.get(self.url, params=params) as resp:
            text = await resp.text()
        async with aopen('request.txt', 'w') as file:
            await file.write(text)
            root = etree.fromstring(text.encode(), etree.XMLParser())
            try:
                interpret = root.xpath("//pod[@title='Input interpretation']"
                                       "/subpod/plaintext/text()")[0]
            except IndexError:
                interpret = ''
            try:
                result = root.xpath("//pod[@title!='Input interpretation']"
                                    "/subpod/plaintext/text()")[0]
            except IndexError:
                result = 'No results found.'
        return f'{interpret}\n{result}'.translate(self.chars)


def setup(bot):
    bot.add_cog(Wolfram(bot))
