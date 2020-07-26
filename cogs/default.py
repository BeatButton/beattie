from io import BytesIO
from typing import Optional

from discord import File, User
from discord.ext import commands
from discord.ext.commands import Cog

from bot import BeattieBot
from context import BContext


class Default(Cog):
    """Default useful commands."""

    @commands.command()
    async def avatar(self, ctx: BContext, user: Optional[User] = None) -> None:
        if user is None:
            user = ctx.author  # type: ignore
        img = BytesIO()
        avatar = user.avatar_url_as(format="png")  # type: ignore
        await avatar.save(img)
        filename = str(avatar).rpartition("/")[2].partition("?")[0]
        await ctx.send(file=File(img, filename))

    @avatar.error
    async def avatar_error(self, ctx: BContext, exc: Exception) -> None:
        if isinstance(exc, commands.BadArgument):
            await ctx.send("User not found.")
        else:
            await ctx.bot.handle_error(ctx, exc)

    @commands.command()
    async def latency(self, ctx: BContext) -> None:
        """Get the latency to the websocket."""
        await ctx.send(f"WS latency: **{ctx.bot.latency*1000:.0f}ms**")

    @commands.command()
    async def ping(self, ctx: BContext) -> None:
        """Get how fast the bot reacts to a command message"""
        msg = await ctx.send("...")
        delta = msg.created_at - ctx.message.created_at
        await msg.edit(content=f":ping_pong: **{delta.total_seconds()*1000:.0f}ms**")
        msg = await ctx.channel.fetch_message(msg.id)
        delta2 = msg.edited_at - ctx.message.created_at  # type: ignore
        await msg.edit(
            content=f"{msg.content}\n**{delta2.total_seconds()*1000:.0f}ms**"
        )

    @commands.command()
    async def source(self, ctx: BContext) -> None:
        """Get the source for the bot."""
        await ctx.send("https://github.com/BeatButton/beattie")

    @commands.command()
    async def invite(self, ctx: BContext) -> None:
        """Get the invite for the bot."""
        url = "<https://discordapp.com/oauth2/authorize?client_id={}&scope=bot>"
        await ctx.send(url.format(ctx.me.id))


def setup(bot: BeattieBot) -> None:
    bot.add_cog(Default())
