from __future__ import annotations

import io
from typing import TYPE_CHECKING, Union

import discord
from discord import AllowedMentions, Embed, File, Message
from discord.ext import commands

if TYPE_CHECKING:
    from bot import BeattieBot


class BContext(commands.Context):
    """An extension of Context to add a reply method and send long content as a file"""

    bot: BeattieBot

    async def reply(
        self,
        content: object = None,
        *,
        tts: bool = False,
        embed: discord.Embed = None,
        file: discord.File = None,
        files: list[discord.File] = None,
        delete_after: float = None,
        nonce: int = None,
        allowed_mentions: discord.AllowedMentions = None,
        reference: Union[discord.Message, discord.MessageReference] = None,
        mention_author: bool = None,
    ) -> discord.Message:
        if mention_author is None:
            mention_author = False
        return await super().reply(
            content,
            tts=tts,
            embed=embed,
            file=file,
            files=files,
            delete_after=delete_after,
            nonce=nonce,
            allowed_mentions=allowed_mentions,
            mention_author=mention_author,
        )

    async def send(
        self,
        content: object = None,
        *,
        tts: bool = False,
        embed: Embed = None,
        file: File = None,
        files: list[File] = None,
        delete_after: float = None,
        nonce: int = None,
        allowed_mentions: AllowedMentions = None,
        reference: Union[Message, discord.MessageReference] = None,
        mention_author: bool = None,
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
            reference=reference,
            mention_author=mention_author,
        )
