from __future__ import annotations

from typing import TYPE_CHECKING, TypeVar

import discord
import httpx
from discord.ext import commands
from discord.ext.commands import Cog

from beattie.utils.contextmanagers import get
from beattie.utils.paginator import Paginator

if TYPE_CHECKING:
    from beattie.bot import BeattieBot
    from beattie.context import BContext


T = TypeVar("T")
V = str | list[str]
LDS = list[dict[str, T]]


class Jisho:
    api_url = "https://jisho.org/api/v1/search/words"

    def __init__(self, session: httpx.AsyncClient):
        self.session = session

    def parse(self, response: LDS[LDS[V]]) -> LDS[list[str]]:
        results = []

        for data in response:
            readings: set[str] = set()
            words: set[str] = set()

            for kanji in data["japanese"]:
                reading = kanji.get("reading")
                assert isinstance(reading, str)
                if reading and reading not in readings:
                    readings.add(reading)

                word = kanji.get("word")
                assert isinstance(word, str)
                if word and word not in words:
                    words.add(word)

            senses: dict[str, list[str]] = {"english": [], "parts_of_speech": []}

            for sense in data["senses"]:
                senses["english"].extend(sense.get("english_definitions", ()))
                senses["parts_of_speech"].extend(sense.get("parts_of_speech", ()))

            try:
                senses["parts_of_speech"].remove("Wikipedia definition")
            except ValueError:
                pass

            result = {"readings": list(readings), "words": list(words), **senses}
            results.append(result)

        return results

    async def lookup(self, keyword: str, **kwargs) -> LDS[list[str]]:
        """Search Jisho.org for a word. Returns a list of dicts with keys
        readings, words, english, parts_of_speech."""
        params = {"keyword": keyword, **kwargs}
        resp = None
        async with get(self.session, self.api_url, params=params) as resp:
            data = resp.json()["data"]

        return self.parse(data)


class Dictionary(Cog):
    jisho_url = "http://jisho.org/search/{}"
    urban_url = "http://api.urbandictionary.com/v0/define"

    def __init__(self, bot: BeattieBot):
        self.jisho = Jisho(session=bot.session)

    @commands.command(name="jisho", aliases=["じしょ", "辞書"])
    async def jisho_(self, ctx: BContext, *, keywords: str):
        """Get results from Jisho.org, Japanese dictionary"""
        async with ctx.typing():
            data = await self.jisho.lookup(keywords)
        if not data:
            await ctx.send("No words found.")
            return
        results = []
        size = len(data)
        for i, res in enumerate(data, 1):
            res = {k: "\n".join(set(v)) or "None" for k, v in res.items()}
            res["english"] = ", ".join(res["english"].split("\n"))
            embed = discord.Embed()
            embed.url = self.jisho_url.format("%20".join(keywords.split()))
            embed.title = keywords
            embed.add_field(name="Words", value=res["words"])
            embed.add_field(name="Readings", value=res["readings"])
            embed.add_field(name="Parts of Speech", value=res["parts_of_speech"])
            embed.add_field(name="Meanings", value=res["english"])
            embed.set_footer(text="Page {}/{}".format(i, size))
            embed.color = discord.Color(0x56D926)
            results.append(embed)
        paginator = Paginator(results)
        await paginator.start(ctx)

    @commands.command(aliases=["ud", "urban", "urbandict"])
    async def urbandictionary(self, ctx: BContext, *, word: str):
        """Look up a word on urbandictionary.com"""
        params = {"term": word}
        get = ctx.bot.get
        async with ctx.typing(), get(self.urban_url, params=params) as resp:
            data = resp.json()
        try:
            results = data["list"]
            results[0]
        except IndexError:
            await ctx.send("Word not found.")
        else:
            embeds = []
            size = len(results)
            for i, res in enumerate(results, 1):
                embed = discord.Embed()
                embed.title = res["word"]
                embed.url = res["permalink"]
                embed.description = res["definition"]
                embed.color = discord.Color(0xE86222)
                embed.set_footer(text="Page {}/{}".format(i, size))
                embeds.append(embed)
            paginator = Paginator(embeds)
            await paginator.start(ctx)


async def setup(bot: BeattieBot):
    await bot.add_cog(Dictionary(bot))
