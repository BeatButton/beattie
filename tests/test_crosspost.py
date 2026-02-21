from __future__ import annotations

import logging
import unittest
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock

import toml

from beattie.__main__ import get_pool
from beattie.bot import BeattieBot
from beattie.cogs.crosspost import Crosspost, sites

if TYPE_CHECKING:
    import discord

    from beattie.utils.type_hints import BotConfig

LOGGER = logging.getLogger("beattie.test.crosspost")


class SiteTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        with open("config/config.toml") as file:
            config: BotConfig = toml.load(file)  # pyright: ignore[reportAssignmentType]
        self.config = config

    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()

        pool = await get_pool(self.config)

        bot = BeattieBot(
            prefixes=tuple(self.config.get("test_prefixes") or self.config["prefixes"]),
            pool=pool,
            debug=True,
        )
        self.bot = bot

        await bot.load_extension("beattie.cogs.crosspost")
        cog = bot.get_cog("Crosspost")
        assert isinstance(cog, Crosspost)
        self.cog = cog

    async def asyncTearDown(self):
        await super().asyncTearDown()
        await self.bot.close()

    def mock_context(self) -> AsyncMock:
        ctx = AsyncMock()
        ctx.guild = None
        ctx.channel.id = id(ctx.channel)
        ctx.message.id = id(ctx.message)

        async def send(
            content: str = None,
            file: discord.File = None,
            files: list[discord.File] = None,
            **_: Any,
        ):
            if content:
                LOGGER.info(content)
            match file, files:
                case None, None:
                    pass
                case file, None:
                    LOGGER.info(file.filename)
                case None, files:
                    LOGGER.info([file.filename for file in files])
                case _, _:
                    msg = "both file and files set"
                    raise RuntimeError(msg)

        ctx.send = send
        ctx.bot = self.bot
        ctx.cog = self.cog
        return ctx


class TwitterTest(SiteTest):
    def setUp(self):
        sites.SITES[:] = [sites.Twitter]
        return super().setUp()

    async def test(self):
        ctx = self.mock_context()
        ctx.message.content = "https://twitter.com/i/status/972064856609210368"
        await self.cog._post(ctx)


if __name__ == "__main__":
    unittest.main()
