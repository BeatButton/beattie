import random
from collections import defaultdict
from typing import Any, Dict, FrozenSet, Iterable, Tuple, Union
from urllib import parse

import discord
from discord import DMChannel, Embed, File, GroupChannel, TextChannel
from discord.ext import commands
from discord.ext.commands import Cog
from lxml import etree

from bot import BeattieBot
from context import BContext

Channel = Union[TextChannel, DMChannel, GroupChannel]


class NSFW(Cog):
    view = {
        "gelbooru": "https://gelbooru.com/index.php?page=post&s=view&id={}",
        "rule34": "https://rule34.xxx/index.php?page=post&s=view&id={}",
        "e621": "http://e621.net/post/show/{}",
    }

    urls = {
        "gelbooru": "http://gelbooru.com/index.php",
        "rule34": "http://rule34.xxx/index.php",
        "e621": "https://e621.net/post/index.xml",
    }

    def cog_check(self, ctx: BContext) -> bool:
        channel: Union[DMChannel, TextChannel] = ctx.channel  # type: ignore
        return isinstance(channel, discord.DMChannel) or channel.is_nsfw()

    def __init__(self, bot: BeattieBot):
        self.cache: Dict[Channel, Dict[str, Dict[FrozenSet[str], Any]]] = defaultdict(
            lambda: defaultdict(dict)
        )
        self.titles: Dict[str, str] = {}
        self.get = bot.get
        self.log = bot.logger.debug

    @commands.command(aliases=["gel"])
    async def gelbooru(self, ctx: BContext, *tags: str) -> None:
        """Search gelbooru for images."""
        await self.booru(ctx, tags)

    @commands.command(aliases=["r34"])
    async def rule34(self, ctx: BContext, *tags: str) -> None:
        """Search rule34.xxx for images."""
        await self.booru(ctx, tags)

    @commands.command(aliases=["fur"])
    async def e621(self, ctx: BContext, *tags: str) -> None:
        """Search e621 for images."""
        await self.booru(ctx, tags, limit=320)

    async def booru(self, ctx: BContext, tags: Iterable[str], limit: int = 100) -> None:
        async with ctx.typing():
            tags = frozenset(tags)
            sort = "order:" in ctx.message.content
            site = ctx.command.name
            channel = ctx.channel
            if site not in self.titles:
                await self.set_metadata(site)
            try:
                posts = self.cache[channel][site][tags]
            except KeyError:
                params = {
                    "page": "dapi",
                    "s": "post",
                    "q": "index",
                    "limit": limit,
                    "tags": " ".join(tags),
                }
                async with ctx.bot.get(self.urls[site], params=params) as resp:
                    root = etree.fromstring(await resp.read())
                posts = root.findall(".//post")
                if sort:
                    posts = posts[::-1]
                else:
                    random.shuffle(posts)
                self.cache[channel][site][tags] = posts
            if not posts:
                await ctx.send("No images found.")
                return
            embed, file = self.make_embed(posts.pop(), site)
            await ctx.send(embed=embed, file=file)
            if not posts:
                self.cache[channel][site].pop(tags, None)

    def make_embed(self, post_element: etree.Element, site: str) -> Tuple[Embed, File]:
        post = dict(post_element.items())
        if not post:
            post = {child.tag: child.text for child in post_element.getchildren()}
        embed = discord.Embed()
        file = discord.File(f"data/favicons/{site}.png", "favicon.png")
        embed.set_thumbnail(url="attachment://favicon.png")
        try:
            image = post["file_url"]
        except KeyError:
            image = post["jpeg_url"]
        if not image.startswith("http"):
            if not image.startswith("//"):
                image = f"//{image}"
            image = f"https:{image}"
        self.log(f"booru url: {image}")
        embed.set_image(url=image)
        embed.title = self.titles[site]
        embed.url = self.view[site].format(post["id"])
        source = post.get("source")
        if source is not None:
            embed.description = f"[source]({source})"
        return embed, file

    async def set_metadata(self, site: str) -> None:
        url = self.urls[site]
        netloc = parse.urlsplit(url).netloc
        async with self.get(f"https://{netloc}") as resp:
            root = etree.fromstring(await resp.read(), etree.HTMLParser())
        self.titles[site] = root.find(".//title").text


def setup(bot: BeattieBot) -> None:
    bot.add_cog(NSFW(bot))
