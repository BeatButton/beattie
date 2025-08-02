from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import re

    from discord.ext.commands import Cooldown

    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Site(ABC):
    cog: Crosspost
    name: str
    pattern: re.Pattern[str]
    cooldown: Cooldown | None = None
    concurrent: bool = True

    def __init__(self, cog: Crosspost):
        self.cog = cog

    async def on_handle(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
    ):
        pass

    @abstractmethod
    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        *args: str,
    ) -> None:
        raise NotImplementedError

    async def load(self) -> None:
        pass

    async def unload(self) -> None:
        pass
