from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Any

import discord
from aiohttp import ClientOSError
from discord import File, Message
from discord.ext import commands

if TYPE_CHECKING:
    from bot import BeattieBot


class BContext(commands.Context):
    """An extension of Context to add a reply method and send long content as a file"""

    bot: BeattieBot

    async def reply(
        self,
        content: str = None,
        *,
        mention_author: bool = None,
        **kwargs: Any,
    ) -> discord.Message:
        if mention_author is None:
            mention_author = False
        return await super().reply(content, mention_author=mention_author, **kwargs)

    async def send(
        self,
        content: str = None,
        *,
        file: File = None,
        files: list[File] = None,
        **kwargs: Any,
    ) -> Message:
        if content and len(content) >= 2000:
            fp = io.BytesIO()
            fp.write(content.encode("utf8"))
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
        kwargs["file"] = file
        kwargs["files"] = files

        try:
            return await super().send(
                content,
                **kwargs,
            )
        except ClientOSError:
            logging.getLogger("beattie.core").exception(
                "Ignoring ClientOSError in BContext.send"
            )
            return await self.send(content, **kwargs)
