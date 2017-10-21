from discord.ext import commands

from lxml import etree
import yaml


class Wolfram:
    chars = {0xf74c: ' d',
             0xf74d: 'e',
             0xf74e: 'i',
             0xf7d9: ' = ',
             }

    def __init__(self):
        self.url = 'http://api.wolframalpha.com/v2/query'
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.key = data['wolfram_key']

    @commands.command(aliases=['wolf', 'w'])
    async def wolfram(self, ctx, *, inp):
        """Query Wolfram|Alpha."""
        async with ctx.typing():
            params = {'input': inp, 'appid': self.key, 'format': 'plaintext'}
            async with ctx.bot.get(self.url, params=params) as resp:
                text = await resp.text()
            root = etree.fromstring(text.encode(), etree.XMLParser())
            interpret = root.xpath("//pod[@title='Input interpretation']"
                                   "/subpod/plaintext/text()")
            if not interpret:
                interpret = root.xpath("//pod[@title='Input']"
                                       "/subpod/plaintext/text()")
            if not interpret:
                interpret = ['']
            interpret = interpret[0]
            try:
                result = root.xpath("//pod[not(@title='Input interpretation' "
                                    "or @title='Input')]"
                                    "/subpod/plaintext/text()")[0]
            except IndexError:
                result = 'No results found.'
            if interpret:
                result = f'{interpret}\n{result}'
            result = result.translate(self.chars)
        await ctx.send(result)


def setup(bot):
    bot.add_cog(Wolfram())
