import re

from lxml import etree

from discord.ext import commands


class Twitter:
    url_expr = re.compile(r'https?:\/\/twitter\.com\/\S+\/status\/\d+')
    selector = './/img[@data-aria-label-part]'

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.__init())

    async def __init(self):
        await self.bot.wait_until_ready()
        if not self.bot.user.bot:
            self.bot.unload_extension(__name__)

    async def on_message(self, message):
        if not (await self.bot.config.get(message.guild.id)).get('twitter'):
            return
        for link in self.url_expr.findall(message.content):
            await self.display_images(link, message.channel)

    async def display_images(self, link, destination):
        async with self.bot.get(link) as resp:
            root = etree.fromstring(await resp.read(), etree.HTMLParser())
        for img_link in root.findall(self.selector)[1:]:
            url = dict(img_link.items())['src']
            await destination.send(f'{url}:large')

    @commands.command()
    async def twitter(self, ctx, enabled: bool=True):
        """Enable or disable sending non-previewed Twitter images."""
        await self.bot.config.set(ctx.guild.id, twitter=enabled)
        fmt = 'en' if enabled else 'dis'
        await ctx.send(f'Sending Twitter images {fmt}abled.')


def setup(bot):
    bot.add_cog(Twitter(bot))
