from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from io import BytesIO
from sys import getsizeof
from typing import TYPE_CHECKING, Any, Self, TypedDict

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
    EmbedFragment | TextFragment | FileFragment | FallbackFragment
)  # spoiler toggle


class FragmentQueue:
    cog: Crosspost
    site: Site
    link: str
    author: str | None
    fragments: list[Fragment]
    handle_task: asyncio.Task | None
    last_used: float  # timestamps
    wait_until: float

    def __init__(self, ctx: CrosspostContext, site: Site, link: str):
        assert ctx.command is not None
        self.site = site
        self.link = link
        self.author = None
        self.cog = ctx.command.cog
        self.fragments = []
        self.wakeup = asyncio.Event()
        self.handle_task = None
        now = datetime.now().timestamp()
        self.last_used = now
        self.wait_until = now

    def __sizeof__(self) -> int:
        return (
            super().__sizeof__()
            + getsizeof(self.link)
            + getsizeof(self.author)
            + getsizeof(self.handle_task)
            + getsizeof(self.last_used)
            + getsizeof(self.wait_until)
            + sum(map(getsizeof, self.fragments))
        )

    async def _handle(self, ctx: CrosspostContext, *args: str):
        cooldown = self.site.cooldown
        if cooldown and (timeout := cooldown.update_rate_limit()):
            self.cog.logger.info(
                f"{self.site.name} ratelimit hit, sleeping for {timeout:.2f} seconds"
            )
            wait_until = datetime.now() + timedelta(seconds=timeout)
            dt = format_dt(wait_until, style="R")
            self.wait_until = wait_until.timestamp()
            await ctx.send(
                f"Global {self.site.name} ratelimit hit, resuming {dt}.",
                delete_after=timeout,
            )
            await asyncio.sleep(timeout)

        await self.site.handler(ctx, self, *args)

    async def handle(self, ctx: CrosspostContext, *args: str) -> Self:
        if self.handle_task is None:
            self.handle_task = asyncio.create_task(self._handle(ctx, *args))

        await self.handle_task
        return self

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
            self,
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
            self,
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
        frag = EmbedFragment(self, embed)
        self.fragments.append(frag)
        return frag

    def push_text(
        self,
        text: str,
        force: bool = False,
        interlaced: bool = False,
        skip_translate: bool = None,
        bold: bool = False,
        italic: bool = False,
        quote: bool = True,
        diminished: bool = False,
    ) -> TextFragment:
        if (
            self.fragments
            and isinstance((frag := self.fragments[-1]), TextFragment)
            and frag.force == force
            and frag.interlaced == interlaced
            and frag.skip_translate == skip_translate
            and frag.bold == bold
            and frag.italic == italic
            and frag.quote == quote
            and frag.diminished == diminished
        ):
            frag.content = f"{frag.content}\n{text}"
        else:
            frag = TextFragment(
                self,
                text,
                force,
                interlaced,
                skip_translate,
                bold,
                italic,
                quote,
                diminished,
            )
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
            settings=settings,
            force=force,
        )

    async def produce(
        self,
        ctx: CrosspostContext,
        *,
        spoiler: bool,
        ranges: list[tuple[int, int]] | None,
        settings: Settings,
    ) -> list[tuple[Postable, bool]]:
        self.last_used = datetime.now().timestamp()
        await self.handle(ctx)
        items: list[tuple[Postable, bool]] = []

        if not self.fragments:
            return items

        if ranges:
            max_pages = 0
            frags = [
                frag
                for frag in self.fragments
                if type(frag).__name__ in ("FileFragment", "FallbackFragment")
            ]
            fragments = [
                frag for start, end in ranges for frag in frags[start - 1 : end]
            ] + [
                frag
                for frag in self.fragments
                if type(frag).__name__ == "TextFragment"
                and (frag.force or not frag.interlaced)  # type: ignore
            ]
        else:
            fragments = self.fragments[:]
            max_pages = settings.max_pages_or_default()

        num_files = 0

        for frag in fragments:
            match frag:
                case TextFragment():
                    if settings.text or frag.force:
                        items.append((frag, spoiler))
                case EmbedFragment():
                    items.append((frag, spoiler))
                case FileFragment() | FallbackFragment():
                    num_files += 1
                    if max_pages != 0 and num_files > max_pages:
                        continue
                    items.append((frag, spoiler))
                case _:
                    raise RuntimeError(
                        f"unexpected Fragment subtype {type(frag).__name__}"
                    )

        pages_remaining = 0 if max_pages == 0 else num_files - max_pages

        if pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            frag = TextFragment(
                self,
                f"{pages_remaining} more item{s} at {self.link}",
                force=True,
                interlaced=False,
            )
            items.append((frag, spoiler))

        return items

    async def present(
        self,
        ctx: CrosspostContext,
        *,
        items: list[tuple[Postable, bool]],
        settings: Settings,
        force: bool,
    ) -> bool:
        to_dl: list[FileFragment] = []
        to_trans: list[TextFragment] = []
        for idx, (item, spoiler) in enumerate(items):
            if type(item).__name__ == "FallbackFragment":
                fall_frag: FallbackFragment = item  # type: ignore
                item = await fall_frag.to_file(ctx)
                items[idx] = item, spoiler
            if type(item).__name__ == "FileFragment":
                to_dl.append(item)  # type: ignore
            if type(item).__name__ == "TextFragment":
                tfrag: TextFragment = item  # type: ignore
                if not tfrag.skip_translate:
                    to_trans.append(tfrag)

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

        if self.site.concurrent:
            for item in to_dl:
                item.save()

        lang = settings.language_or_default()

        for item in to_trans:
            item.translate(lang)

        embedded = False

        file_batch: list[File] = []
        limit = get_size_limit(ctx)

        async def send_files():
            nonlocal embedded
            if file_batch:
                embedded = True
                await ctx.send(files=file_batch)
                file_batch.clear()

        async def send_text(frag: TextFragment):
            if not frag.skip_translate and (translated := await frag.translate(lang)):
                diminished = frag.format(diminished=True)
                content = frag.format(translated)
                quote = "> " if frag.quote else ""
                text = (
                    f"{diminished}\n{quote}-# <:trans:1289284212372934737>\n{content}"
                )
            else:
                text = frag.format()

            if text:
                if spoiler:
                    text = f"||{text}||"

                await ctx.send(text, suppress_embeds=True)

        try:
            for item, spoiler in items:
                match type(item).__name__:
                    case "TextFragment":
                        tfrag: TextFragment = item  # type: ignore
                        await send_files()
                        if tfrag.force:
                            await ctx.send(tfrag.content, suppress_embeds=True)
                        else:
                            await send_text(tfrag)
                    case "EmbedFragment":
                        await send_files()
                        efrag: EmbedFragment = item  # type: ignore
                        await ctx.send(embed=efrag.embed)
                    case "FileFragment":
                        frag: FileFragment = item  # type: ignore
                        if to_file := getattr(frag, "to_file", None):
                            frag = await to_file(ctx)
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
