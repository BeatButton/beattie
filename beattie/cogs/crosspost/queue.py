from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from sys import getsizeof
from typing import TYPE_CHECKING, Any, Awaitable, TypedDict

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
    from .sites import Site


class QueueKwargs(TypedDict):
    spoiler: bool
    force: bool
    ranges: list[tuple[int, int]] | None
    settings: Settings


Postable = (
    str | discord.Embed | tuple[FileFragment | FallbackFragment, bool]
)  # spoiler toggle


class FragmentQueue:
    cog: Crosspost
    site: Site
    link: str
    author: str | None
    fragments: list[Fragment]
    resolved: asyncio.Event
    handle_task: asyncio.Task | None
    last_used: float  # timestamp

    def __init__(self, ctx: CrosspostContext, site: Site, link: str):
        assert ctx.command is not None
        self.site = site
        self.link = link
        self.author = None
        self.cog = ctx.command.cog
        self.fragments = []
        self.resolved = asyncio.Event()
        self.handle_task = None
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

    def handle(self, ctx: CrosspostContext, *args: str) -> asyncio.Task[None]:
        if self.handle_task is None:
            self.handle_task = asyncio.create_task(self.site.handler(ctx, self, *args))

        return self.handle_task

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

    async def perform(
        self,
        ctx: CrosspostContext,
        *,
        spoiler: bool,
        force: bool,
        ranges: list[tuple[int, int]] | None,
        settings: Settings,
    ) -> bool:
        items = await self.produce(
            ctx,
            spoiler=spoiler,
            ranges=ranges,
            settings=settings,
        )
        return await self.present(
            ctx,
            items=items,
            force=force,
        )

    async def produce(
        self,
        ctx: CrosspostContext,
        *,
        spoiler: bool,
        ranges: list[tuple[int, int]] | None,
        settings: Settings,
    ) -> list[Postable]:
        self.last_used = datetime.now().timestamp()
        await self.handle(ctx)
        items: list[Postable] = []

        if not self.fragments:
            return items

        text = ""

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

        if settings.text:

            def queue_text():
                nonlocal text
                send = text.strip()
                text = ""
                if send:
                    if spoiler:
                        send = f"||{send}||"
                    items.append(send)

        else:

            def queue_text():
                pass

        num_files = 0

        for frag in fragments:
            match frag:
                case TextFragment():
                    if frag.force:
                        queue_text()
                        items.append(frag.content)
                    else:
                        text = f"{text}\n{frag.content}"
                case EmbedFragment():
                    queue_text()
                    embed = frag.embed
                    if spoiler:
                        embed = embed.copy()
                        embed.set_image(url=None)
                    items.append(embed)
                case FileFragment() | FallbackFragment():
                    num_files += 1
                    if max_pages != 0 and num_files > max_pages:
                        continue
                    queue_text()
                    items.append((frag, spoiler))
                case _:
                    raise RuntimeError(
                        f"unexpected Fragment subtype {type(frag).__name__}"
                    )

        queue_text()

        pages_remaining = 0 if max_pages == 0 else num_files - max_pages

        if pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            message = f"{pages_remaining} more item{s} at {self.link}"
            items.append(message)

        return items

    @classmethod
    async def present(
        cls,
        ctx: CrosspostContext,
        *,
        items: list[Postable],
        force: bool,
    ) -> bool:
        to_dl: list[FileFragment] = []
        for idx, item in enumerate(items):
            if isinstance(item, tuple):
                frag, spoiler = item
                if isinstance(frag, FallbackFragment):
                    frag = await frag.to_file(ctx)
                    items[idx] = frag, spoiler
                if isinstance(frag, FileFragment):
                    to_dl.append(frag)

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

        for item in to_dl:
            item.save()

        embedded = False

        file_batch: list[File] = []
        limit = get_size_limit(ctx)

        async def send_files():
            nonlocal embedded
            if file_batch:
                embedded = True
                await ctx.send(files=file_batch)
                file_batch.clear()

        try:
            for item in items:
                match item:
                    case str():
                        await send_files()
                        await ctx.send(item, suppress_embeds=True)
                    case discord.Embed():
                        await send_files()
                        await ctx.send(embed=item)
                    case (frag, spoiler):
                        if isinstance(frag, FallbackFragment):
                            frag = await frag.to_file(ctx)
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
                    case _:
                        raise RuntimeError(
                            f"unexpected item of type {type(item).__name__}"
                        )
        finally:
            await send_files()

        return embedded
