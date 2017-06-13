import discord
from discord.ext import commands
import yaml


class OSU:
    def __init__(self):
        with open('config/config.yaml') as file:
            data = yaml.load(file)
        self.key = data['osu_key']
        self.base = 'https://osu.ppy.sh/'

    @commands.group()
    async def osu(self, ctx):
        """Commands for getting data about OSU! Feedback appreciated."""
        if ctx.invoked_subcommand is None:
            await ctx.send('Invalid command passed. '
                           f'Try "{ctx.prefix}help osu"')

    @osu.command(aliases=['u'])
    async def user(self, ctx, name=None):
        if name is None:
            name = ctx.author.display_name
        url = 'api/get_user'
        params = {'k': self.key, 'u': name}
        async with ctx.bot.get(f'{self.base}{url}', params=params) as resp:
            data = await resp.json()
        if not data:
            await ctx.send(f'No user with name or id {name} found.')
            return
        data = data[0]
        profile = f'{self.base}u/{data["user_id"]}'
        avatar = f'https://a.ppy.sh/{data["user_id"]}'
        rank = f'#{int(data["pp_rank"]):3,}'
        accuracy = f'{float(data["accuracy"]):.2f}%'
        level = data['level'].partition('.')[0]

        embed = discord.Embed()
        embed.title = 'OSU!'
        embed.url = profile
        embed.set_author(name=data['username'], icon_url=avatar)
        embed.add_field(inline=False, name='Rank', value=rank)
        embed.add_field(inline=False, name='Level', value=level)
        embed.add_field(inline=False, name='Accuracy', value=accuracy)

        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(OSU())
