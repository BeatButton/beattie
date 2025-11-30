from __future__ import annotations

from typing import TYPE_CHECKING

from . import sites
from .cog import Crosspost

if TYPE_CHECKING:
    from beattie.bot import BeattieBot

__all__ = ["sites"]


async def setup(bot: BeattieBot):
    await bot.add_cog(Crosspost(bot))
