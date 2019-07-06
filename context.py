import io

import discord
from discord.ext import commands

from utils import contextmanagers


class BContext(commands.Context):
    """An extension of Context to add reply and mention methods,
    as well as support use with self bots"""

    async def reply(self, content, sep=",\n", **kwargs):
        if self.me.bot and self.guild:
            content = f"{self.author.display_name}{sep}{content}"
        return await self.send(content, **kwargs)

    async def mention(self, content, sep=",\n", **kwargs):
        if self.me.bot and self.guild:
            content = f"{self.author.mention}{sep}{content}"
        return await self.send(content, **kwargs)

    async def send(self, content=None, *, embed=None, **kwargs):
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
        if self.me.bot:
            return await super().send(content, embed=embed, **kwargs)
        else:
            edit_content = self.message.content
            if content is not None:
                edit_content = f"{edit_content}\n{content}"
            if content or embed:
                await self.message.edit(content=edit_content, embed=embed)
            if kwargs:
                return await super().send(**kwargs)
            return self.message

    def typing(self):
        if self.me.bot:
            return super().typing()
        else:
            return contextmanagers.null()
