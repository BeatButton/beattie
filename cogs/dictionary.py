from asyncjisho import Jisho

import discord
from discord.ext import commands

from utils.paginator import Paginator

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
        results = []
        size = len(data)
        for i, res in enumerate(data, 1):
            res = {k: '\n'.join(v) or 'None' for k, v in res.items()}
            res['english'] = ', '.join(res['english'].split('\n'))
            embed = discord.Embed()
            embed.url = self.jisho_url.format('%20'.join(keywords.split()))
            embed.title = keywords
            embed.add_field(name='Words', value=res['words'])
            embed.add_field(name='Readings', value=res['readings'])
            embed.add_field(name='Parts of Speech', value=res['parts_of_speech'])
            embed.add_field(name='Meanings', value=res['english'])
            embed.set_footer(text="Page {}/{}".format(i, size))
            embed.color = discord.Color(0x56d926)
            results.append(embed)
        paginator = Paginator(ctx, results)
        await paginator.run()

    @commands.command(aliases=['ud', 'urban', 'urbandict'])
    async def urbandictionary(self, ctx, *, word):
        """Look up a word on urbandictionary.com"""
        params = {'term': word}
        get = ctx.bot.get
        async with ctx.typing(), get(self.urban_url, params=params) as resp:
                data = await resp.json()
        try:
            results = data['list']
            results[0]
        except IndexError:
            await ctx.send('Word not found.')
        else:
            embeds = []
            size = len(results)
            for i, res in enumerate(results, 1):
                embed = discord.Embed()
                embed.title = res['word']
                embed.url = res['permalink']
                embed.description = res['definition']
                embed.color = discord.Color(0xe86222)
                embed.set_footer(text='Page {}/{}'.format(i, size))
                embeds.append(embed)
            paginator = Paginator(ctx, embeds)
            await paginator.run()


def setup(bot):
    bot.add_cog(Dictionary(bot))
