from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from sys import getsizeof
from typing import TYPE_CHECKING, Any

from discord import Embed, File
from discord.utils import format_dt
import discord

from beattie.utils.etc import display_bytes, get_size_limit

from .fragment import (
    Fragment,
    FileFragment,
    FallbackFragment,
    EmbedFragment,
    TextFragment,
)

if TYPE_CHECKING:
    from .cog import Crosspost
    from .context import CrosspostContext
    from .database import Settings
    from .postprocess import PP


class FragmentQueue:
    cog: Crosspost
    link: str
    fragments: list[Fragment]
    resolved: asyncio.Event
    last_used: float  # timestamp

    def __init__(self, ctx: CrosspostContext, link: str):
        assert ctx.command is not None
        self.link = link
        self.cog = ctx.command.cog
        self.fragments = []
        self.resolved = asyncio.Event()
        self.last_used = datetime.now().timestamp()

    def __sizeof__(self) -> int:
        return (
            super().__sizeof__()
            + getsizeof(self.cog)
            + getsizeof(self.link)
            + getsizeof(self.resolved)
            + getsizeof(self.last_used)
            + sum(map(getsizeof, self.fragments))
        )

    def push_file(
        self,
        *urls: str,
        filename: str = None,
        postprocess: PP = None,
        pp_extra: Any = None,
        can_link: bool = True,
        headers: dict[str, str] = None,
    ) -> FileFragment:
        frag = FileFragment(
            self.cog,
            *urls,
            filename=filename,
            postprocess=postprocess,
            pp_extra=pp_extra,
            headers=headers,
            lock_filename=filename is not None,
            can_link=can_link,
        )
        self.fragments.append(frag)
        return frag

    def push_fallback(
        self,
        preferred_url: str,
        fallback_url: str,
        headers: dict[str, str],
    ) -> FallbackFragment:
        frag = FallbackFragment(
            self.cog,
            preferred_url,
            fallback_url,
            headers,
        )
        self.fragments.append(frag)
        return frag

    def push_embed(
        self,
        embed: Embed,
    ) -> EmbedFragment:
        frag = EmbedFragment(embed)
        self.fragments.append(frag)
        return frag

    def push_text(
        self,
        text: str,
        force: bool = False,
        interlaced: bool = False,
    ) -> TextFragment:
        frag = TextFragment(text, force, interlaced)
        self.fragments.append(frag)
        return frag

    def clear(self):
        self.fragments.clear()

    async def resolve(
        self,
        ctx: CrosspostContext,
        *,
        spoiler: bool,
        force: bool,
        ranges: list[tuple[int, int]] | None,
        settings: Settings,
    ) -> bool:
        self.resolved.set()
        return await self.perform(
            ctx,
            spoiler=spoiler,
            force=force,
            ranges=ranges,
            settings=settings,
        )

    async def perform(
        self,
        ctx: CrosspostContext,
        *,
        spoiler: bool,
        force: bool,
        ranges: list[tuple[int, int]] | None,
        settings: Settings,
    ) -> bool:
        self.last_used = datetime.now().timestamp()
        await self.resolved.wait()

        if not self.fragments:
            return False

        to_dl: list[FileFragment] = []
        limit = get_size_limit(ctx)
        text = ""
        file_batch: list[File] = []

        if ranges:
            max_pages = 0
            frags = [
                frag
                for frag in self.fragments
                if isinstance(frag, (FileFragment, FallbackFragment))
            ]
            fragments = [
                frag for start, end in ranges for frag in frags[start - 1 : end]
            ] + [
                frag
                for frag in self.fragments
                if isinstance(frag, TextFragment)
                and (frag.force or not frag.interlaced)
            ]
        else:
            fragments = self.fragments[:]
            max_pages = settings.max_pages_or_default()
        do_text = settings.text

        for idx, frag in enumerate(fragments):
            if isinstance(frag, FallbackFragment):
                fragments[idx] = frag = await frag.to_file(ctx)
            if isinstance(frag, FileFragment):
                to_dl.append(frag)
            if max_pages and len(to_dl) >= max_pages:
                break

        if not force and len(to_dl) >= 25:

            def check(r: discord.Reaction, u: discord.User):
                return (
                    u == ctx.author
                    and r.message == msg
                    and (r.emoji == "❌" or r.emoji == "⭕")
                )

            timeout = 60
            dt = format_dt(datetime.now() + timedelta(seconds=timeout), style="R")
            msg = await ctx.reply(
                f"This post has {len(to_dl)} items. Are you sure? React {dt}."
                "\n-# You can post specific pages with a command like "
                "`b>post pages=1-3,5,7,12-16`",
                mention_author=True,
            )
            for emoji in "⭕❌":
                asyncio.create_task(msg.add_reaction(emoji))

            try:
                reaction, _ = await ctx.bot.wait_for(
                    "reaction_add", check=check, timeout=timeout
                )
            except asyncio.TimeoutError:
                emoji = "❌"
            else:
                emoji = reaction.emoji

            await msg.delete()
            if emoji == "❌":
                return False

        for frag in to_dl:
            frag.save()

        embedded = False

        async def send_files():
            nonlocal embedded
            if file_batch:
                embedded = True
                await ctx.send(files=file_batch)
                file_batch.clear()

        async def send_text():
            nonlocal text
            send = text.strip()
            text = ""
            if send:
                if spoiler:
                    send = f"||{send}||"
                await ctx.send(send, suppress_embeds=True)

        num_files = 0
        try:
            for frag in fragments:
                match frag:
                    case TextFragment():
                        if frag.force:
                            await send_files()
                            await ctx.send(frag.content, suppress_embeds=True)
                        else:
                            text = f"{text}\n{frag}"
                    case EmbedFragment():
                        await send_files()
                        if do_text:
                            await send_text()
                        embed = frag.embed
                        if spoiler:
                            embed = embed.copy()
                            embed.set_image(url=None)
                        await ctx.send(embed=embed)
                    case FileFragment():
                        num_files += 1
                        if max_pages and num_files > max_pages:
                            continue
                        if do_text:
                            await send_text()
                        await frag.save()
                        file_bytes = frag.file_bytes
                        if not file_bytes:
                            raise RuntimeError("frag.save failed to set file_bytes")
                        size = len(file_bytes)
                        if size > limit:
                            await send_files()
                            if frag.can_link:
                                url = frag.urls[0]
                                if spoiler:
                                    url = f"||{url}||"
                                await ctx.send(url)
                                embedded = True
                            else:
                                await ctx.send(
                                    f"File too large to upload ({display_bytes(size)})."
                                )
                            continue
                        if len(file_batch) == 10:
                            await send_files()
                        file_batch.append(
                            File(BytesIO(file_bytes), frag.filename, spoiler=spoiler)
                        )
                    case FallbackFragment():
                        if num_files < max_pages:
                            raise RuntimeError("hit a FallbackFragment with pages left")
                        num_files += 1
                    case _:
                        raise RuntimeError(
                            f"unexpected Fragment subtype {type(frag).__name__}"
                        )
        finally:
            if file_batch:
                await send_files()

            if do_text:
                await send_text()

        pages_remaining = max_pages and num_files - max_pages

        if pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            message = f"{pages_remaining} more item{s} at {self.link}"
            await ctx.send(message, suppress_embeds=True)

        return embedded
