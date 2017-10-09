from asyncjisho import Jisho

import discord
from discord.ext import commands


class Dictionary:
    jisho_url = 'http://jisho.org/search/{}'
    urban_url = 'http://api.urbandictionary.com/v0/define'

    def __init__(self, bot):
        self.jisho = Jisho(session=bot.session)

    @commands.command(name='jisho')
    async def jisho_(self, ctx, *, keywords):
        """Get results from Jisho.org, Japanese dictionary"""
        async with ctx.typing():
            data = await self.jisho.lookup(keywords)
        if not data:
            await ctx.send('No words found.')
            return
        res = data[0]
        res = {k: '\n'.join(v) for k, v in res.items()}
        res['english'] = ', '.join(res['english'].split('\n'))
        embed = discord.Embed()
        embed.url = self.jisho_url.format('%20'.join(keywords.split()))
        embed.title = keywords
        res = {k: self.format(v) for k, v in res.items()}
        embed.add_field(name='Words', value=res['words'])
        embed.add_field(name='Readings', value=res['readings'])
        embed.add_field(name='Parts of Speech', value=res['parts_of_speech'])
        embed.add_field(name='Meanings', value=res['english'])
        embed.color = discord.Color(0x56d926)
        await ctx.send(embed=embed)

    @commands.command(aliases=['ud', 'urban', 'urbandict'])
    async def urbandictionary(self, ctx, *, word):
        """Look up a word on urbandictionary.com"""
        params = {'term': word}
        get = ctx.bot.get
        async with ctx.typing(), get(self.urban_url, params=params) as resp:
                data = await resp.json()
        try:
            res = data['list'][0]
        except IndexError:
            await ctx.send('Word not found.')
        else:
            embed = discord.Embed()
            embed.title = res['word']
            embed.url = res['permalink']
            embed.description = res['definition']
            embed.color = discord.Color(0xe86222)
            await ctx.send(embed=embed)

    @staticmethod
    def format(val):
        return val if val else 'None'


def setup(bot):
    bot.add_cog(Dictionary(bot))
