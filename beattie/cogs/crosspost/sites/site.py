from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from discord.ext.commands import Cooldown

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Site(ABC):
    cog: Crosspost
    name: str
    pattern: re.Pattern[str]
    cooldown: Cooldown | None = None

    def __init__(self, cog: Crosspost):
        self.cog = cog

    @abstractmethod
    async def handler(
        self, ctx: CrosspostContext, queue: FragmentQueue, *args: str
    ) -> None:
        raise NotImplementedError

    async def load(self) -> None:
        pass

    async def unload(self) -> None:
        pass
