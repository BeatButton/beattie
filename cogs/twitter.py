import re

from lxml import etree

from discord.ext import commands


class Twitter:
    url_expr = re.compile(r'https?:\/\/twitter\.com\/\S+\/status\/\d+')
    selector = (".//img[@data-aria-label-part]")

    def __init__(self, bot):
        self.bot = bot

    async def on_message(self, message):
        if not (await self.bot.config.get(message.guild.id))['twitter']:
            return
        for link in self.url_expr.findall(message.content):
            await self.display_images(link, message.channel)

    async def display_images(self, link, destination):
        async with self.bot.get(link) as resp:
            root = etree.fromstring(await resp.read(), etree.HTMLParser())
        for img_link in root.findall(self.selector)[1:]:
            await destination.send(dict(img_link.items())['src'])

    @commands.command()
    async def twitter(self, ctx, enabled: bool=True):
        """Enable or disable sending non-previewed Twitter images."""
        await self.bot.config.set(ctx.guild.id, twitter=enabled)
        fmt = 'en' if enabled else 'dis'
        await ctx.send(f'Sending Twitter images {fmt}abled.')


def setup(bot):
    bot.add_cog(Twitter(bot))
