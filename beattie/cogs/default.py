from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

from discord import File, Member, User
from discord.ext import commands
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext


class Default(Cog):
    """Default useful commands."""

    @commands.command()
    async def avatar(
        self,
        ctx: BContext,
        user: Member | User = commands.Author,
        which: str = "server",
    ):
        """Get someone's avatar

        Optionally, specify "which" avatar you want: server, global, or default"""
        img = BytesIO()
        match which:
            case "server" | "guild" | "local":
                avatar = user.display_avatar.with_format(
                    "gif" if user.display_avatar.is_animated() else "png",
                )
            case "global":
                asset = user.avatar or user.display_avatar
                avatar = asset.with_format("gif" if asset.is_animated() else "png")
            case "default":
                avatar = user.default_avatar.with_format("png")
            case _:
                await ctx.send(f'"{which}" is not a type of avatar.')
                return
        await avatar.save(img)
        filename = str(avatar).rpartition("/")[2].partition("?")[0]
        await ctx.send(file=File(img, filename))

    @avatar.error
    async def avatar_error(self, ctx: BContext, exc: Exception):
        if isinstance(exc, commands.BadUnionArgument):
            await ctx.send("User not found.")
        else:
            await ctx.bot.handle_error(ctx, exc)

    @commands.command()
    async def icon(self, ctx: BContext):
        """Get the server icon"""
        icon = ctx.guild and ctx.guild.icon
        if icon is None:
            await ctx.send("This server has no icon.")
            return
        img = BytesIO()
        await icon.save(img)
        filename = str(icon).rpartition("/")[2].partition("?")[0]
        await ctx.send(file=File(img, filename))

    @commands.command()
    async def latency(self, ctx: BContext):
        """Get the latency to the websocket."""
        await ctx.send(f"WS latency: **{ctx.bot.latency*1000:.0f}ms**")

    @commands.command()
    async def ping(self, ctx: BContext):
        """Get how fast the bot reacts to a command message"""
        msg = await ctx.send("...")
        delta = msg.created_at - ctx.message.created_at
        await msg.edit(content=f":ping_pong: **{delta.total_seconds()*1000:.0f}ms**")
        msg = await ctx.channel.fetch_message(msg.id)
        edited_at = msg.edited_at
        assert edited_at is not None
        delta2 = edited_at - ctx.message.created_at
        await msg.edit(
            content=f"{msg.content}\n**{delta2.total_seconds()*1000:.0f}ms**",
        )

    @commands.command()
    async def source(self, ctx: BContext):
        """Get the source for the bot."""
        await ctx.send("https://github.com/BeatButton/beattie")

    @commands.command()
    async def invite(self, ctx: BContext):
        """Get the invite for the bot."""
        url = (
            "<https://discordapp.com/oauth2/authorize?"
            "client_id=1390347718227923107&scope=bot&permissions=274878295104>"
        )
        await ctx.send(url.format(ctx.me.id))


async def setup(bot: BeattieBot):
    await bot.add_cog(Default())
