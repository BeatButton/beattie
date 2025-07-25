from __future__ import annotations

import logging
import random
from base64 import b64encode
from collections import defaultdict
from types import MappingProxyType
from typing import TYPE_CHECKING, Any
from urllib import parse

import toml
from lxml import etree

import discord
from discord import Embed, File, TextChannel
from discord.ext import commands
from discord.ext.commands import Cog

if TYPE_CHECKING:
    from collections.abc import Iterable

    from discord.abc import MessageableChannel

    from beattie.bot import BeattieBot
    from beattie.context import BContext


class NSFW(Cog):
    view = MappingProxyType(
        {
            "gelbooru": "https://gelbooru.com/index.php?page=post&s=view&id={}",
            "rule34": "https://rule34.xxx/index.php?page=post&s=view&id={}",
            "e621": "http://e621.net/posts/{}",
        },
    )

    urls = MappingProxyType(
        {
            "gelbooru": "http://gelbooru.com/index.php",
            "rule34": "http://rule34.xxx/index.php",
            "e621": "https://e621.net/posts.json",
        },
    )

    def cog_check(self, ctx: BContext) -> bool:
        channel = ctx.channel
        if isinstance(channel, TextChannel):
            return channel.is_nsfw()
        return True

    def __init__(self, bot: BeattieBot):
        self.cache: dict[MessageableChannel, dict[str, dict[frozenset[str], Any]]] = (
            defaultdict(lambda: defaultdict(dict))
        )
        self.titles: dict[str, str] = {}
        self.get = bot.get
        self.logger = logging.getLogger(__name__)
        self.parser = etree.HTMLParser()
        try:
            with open("config/crosspost/e621.toml") as fp:
                data = toml.load(fp)
            self.e621_key = data["api_key"]
            self.e621_user = data["user"]
        except FileNotFoundError:
            self.e621_key = ""
            self.e621_user = ""

    @commands.command(aliases=["gel"])
    async def gelbooru(self, ctx: BContext, *tags: str):
        """Search gelbooru for images."""
        await self.booru(ctx, tags)

    @commands.command(aliases=["r34"])
    async def rule34(self, ctx: BContext, *tags: str):
        """Search rule34.xxx for images."""
        await self.booru(ctx, tags)

    @commands.command(aliases=["fur"])
    async def e621(self, ctx: BContext, *tags: str):
        """Search e621 for images."""
        await self.booru(ctx, tags, limit=320)

    async def booru(self, ctx: BContext, tags: Iterable[str], limit: int = 100):
        assert ctx.command is not None
        async with ctx.typing():
            tags = frozenset(tags)
            site = ctx.command.name
            channel = ctx.channel
            if site not in self.titles:
                await self.set_metadata(site)
            try:
                posts = self.cache[channel][site][tags]
            except KeyError:
                if site == "e621":
                    params = {"limit": limit, "tags": " ".join(tags)}
                    if self.e621_key:
                        auth_slug = b64encode(
                            f"{self.e621_user}:{self.e621_key}".encode(),
                        ).decode()
                        headers = {"Authorization": f"Basic {auth_slug}"}
                    else:
                        headers = {}
                    async with ctx.bot.get(
                        self.urls[site],
                        params=params,
                        headers=headers,
                    ) as resp:
                        data = resp.json()
                    posts = [
                        {
                            "file_url": url,
                            "id": post["id"],
                        }
                        for post in data["posts"]
                        if (url := post["file"]["url"])
                    ]
                else:
                    params = {
                        "page": "dapi",
                        "s": "post",
                        "q": "index",
                        "limit": limit,
                        "tags": " ".join(tags),
                    }
                    async with ctx.bot.get(self.urls[site], params=params) as resp:
                        root = etree.fromstring(resp.content, self.parser)
                    posts = root.findall(".//post")
                random.shuffle(posts)
                self.cache[channel][site][tags] = posts
            if not posts:
                await ctx.send("No images found.")
                return
            embed, file = self.make_embed(posts.pop(), site)
            await ctx.send(embed=embed, file=file)
            if not posts:
                self.cache[channel][site].pop(tags, None)

    def make_embed(
        self,
        post: etree.Element | dict,  # type: ignore
        site: str,
    ) -> tuple[Embed, File]:
        if not isinstance(post, dict):
            post = dict(post.items()) or {
                child.tag: child.text for child in post.getchildren()
            }
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
        self.logger.debug("booru url: %s", image)
        embed.set_image(url=image)
        embed.title = self.titles[site]
        embed.url = self.view[site].format(post["id"])
        source = post.get("source")
        if source is not None:
            embed.description = f"[source]({source})"
        return embed, file

    async def set_metadata(self, site: str):
        url = self.urls[site]
        netloc = parse.urlsplit(url).netloc
        async with self.get(f"https://{netloc}") as resp:
            root = etree.fromstring(resp.content, self.parser)
        self.titles[site] = root.find(".//title").text


async def setup(bot: BeattieBot):
    await bot.add_cog(NSFW(bot))
