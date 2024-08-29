from __future__ import annotations

from typing import TYPE_CHECKING, Any

from discord import Message

from beattie.context import BContext

if TYPE_CHECKING:
    from .cog import Crosspost


class CrosspostContext(BContext):
    cog: Crosspost

    async def send(self, content: str = None, **kwargs: Any) -> Message:
        msg = await super().send(
            content,
            **kwargs,
        )

        await self.cog.db.add_sent_message(self.message.id, msg.id)

        return msg
