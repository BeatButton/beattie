from discord.ext import commands

from lxml import etree
import yaml

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
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.key = data['wolfram_key']

    @commands.command(aliases=['wolf', 'w'])
    async def wolfram(self, ctx, *, inp):
        """Query Wolfram|Alpha."""
        async with ctx.typing():
            params = {'input': inp, 'appid': self.key, 'format': 'plaintext'}
            async with self.bot.get(self.url, params=params) as resp:
                text = await resp.text()
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
            if interpret:
                result = f'{interpret}\n{result}'
            result = result.translate(self.chars)
        await ctx.send(result)


def setup(bot):
    bot.add_cog(Wolfram(bot))
