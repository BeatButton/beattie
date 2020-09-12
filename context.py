from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any, Optional

import discord
from discord import Embed, Message
from discord.ext import commands

if TYPE_CHECKING:
    from bot import BeattieBot


class BContext(commands.Context):
    """An extension of Context to add a reply method and send long content as a file"""

    bot: BeattieBot

    async def reply(self, content: str, sep: str = ",\n", **kwargs: Any) -> Message:
        if self.guild:
            content = f"{self.author.display_name}{sep}{content}"
        return await self.send(content, **kwargs)

    async def send(  # type: ignore
        self,
        content: Optional[str] = None,
        *,
        embed: Optional[Embed] = None,
        **kwargs: Any,
    ) -> Message:
        str_content = str(content)
        if len(str_content) >= 2000:
            fp = io.BytesIO()
            fp.write(str_content.encode("utf8"))
            fp.seek(0)
            content = None
            file = discord.File(fp, filename=f"{self.message.id}.txt")
            if kwargs.get("files") is not None:
                kwargs["files"].append(file)
            else:
                kwargs["file"] = file
        return await super().send(content, embed=embed, **kwargs)
