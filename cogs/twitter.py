import re

from lxml import etree

from discord.ext import commands


class Twitter:
    url_expr = re.compile(r'https?:\/\/twitter\.com\/\S+\/status\/\d+')
    tweet_selector = ".//div[contains(@class, 'tweet permalink-tweet')]"
    img_selector = './/img[@data-aria-label-part]'

    def __init__(self, bot):
        self.bot = bot
        self.bot.loop.create_task(self.__init())
        self.headers = {'User-Agent':
                        'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/41.0.2228.0 Safari/537.36'}

    async def __init(self):
        await self.bot.wait_until_ready()
        if not self.bot.user.bot:
            self.bot.unload_extension(__name__)

    async def on_message(self, message):
        if message.guild is None:
            return
        if not (await self.bot.config.get(message.guild.id)).get('twitter'):
            return
        for link in self.url_expr.findall(message.content):
            await self.display_images(link, message.channel)

    async def display_images(self, link, destination):
        async with self.bot.get(link, headers=self.headers) as resp:
            root = etree.fromstring(await resp.read(), etree.HTMLParser())
        try:
            tweet = root.xpath(self.tweet_selector)[0]
        except IndexError:
            return
        for img_link in tweet.findall(self.img_selector)[1:]:
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
