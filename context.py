from __future__ import annotations

import io
from typing import TYPE_CHECKING, Any, Optional

import discord
from discord import AllowedMentions, Embed, File, Message
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

    async def send(
        self,
        content: Optional[object] = None,
        *,
        tts: bool = False,
        embed: Optional[Embed] = None,
        file: Optional[File] = None,
        files: Optional[list[File]] = None,
        delete_after: Optional[float] = None,
        nonce: Optional[int] = None,
        allowed_mentions: Optional[AllowedMentions] = None,
    ) -> Message:
        str_content = str(content)
        if len(str_content) >= 2000:
            fp = io.BytesIO()
            fp.write(str_content.encode("utf8"))
            fp.seek(0)
            content = None
            new_file = discord.File(fp, filename=f"{self.message.id}.txt")
            if files is not None:
                files.append(new_file)
            elif file is not None:
                files = [file, new_file]
                file = None
            else:
                file = new_file
        return await super().send(
            content,
            tts=tts,
            embed=embed,
            file=file,
            files=files,
            delete_after=delete_after,
            nonce=nonce,
            allowed_mentions=allowed_mentions,
        )
