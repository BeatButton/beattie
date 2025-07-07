from __future__ import annotations

import asyncio
import time
from datetime import datetime
from io import BytesIO
from itertools import groupby
from sys import getsizeof
from typing import TYPE_CHECKING, Any, Self, TypedDict

import discord
from discord import Embed, File
from discord.utils import format_dt

from beattie.utils.etc import INVITE_EXPR, display_bytes, get_size_limit

from .fragment import (
    EmbedFragment,
    FallbackFragment,
    FileFragment,
    Fragment,
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
    handle_task: asyncio.Task[Self] | None
    last_used: float  # timestamps
    wait_until: float

    def __init__(self, ctx: CrosspostContext, site: Site, link: str):
        assert ctx.command is not None
        self.site = site
        self.link = link
        self.author = None
        self.cog = ctx.command.cog
        self.fragments = []
        self.handle_task = None
        now = time.time()
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

    async def _handle(self, ctx: CrosspostContext, *args: str) -> Self:
        cooldown = self.site.cooldown
        if cooldown and (timeout := cooldown.update_rate_limit()):
            self.cog.logger.info(
                "%s ratelimit hit, sleeping for %f seconds",
                self.site.name,
                timeout,
            )
            wait_until = time.time() + timeout
            dt = format_dt(
                datetime.fromtimestamp(wait_until),  # noqa: DTZ006
                style="R",
            )
            self.wait_until = wait_until
            await ctx.send(
                f"Global {self.site.name} ratelimit hit, resuming {dt}.",
                delete_after=timeout,
            )
            await asyncio.sleep(timeout)

        await self.site.handler(ctx, self, *args)
        return self

    async def handle(self, ctx: CrosspostContext, *args: str) -> Self:
        if self.handle_task is None:
            self.handle_task = asyncio.create_task(self._handle(ctx, *args))

        return await self.handle_task

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
        escape: bool = True,
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
            and frag.escape == escape
        ):
            frag.content = f"{frag.content}\n{text}"
        else:
            frag = TextFragment(
                self,
                text,
                force=force,
                interlaced=interlaced,
                skip_translate=skip_translate,
                bold=bold,
                italic=italic,
                quote=quote,
                diminished=diminished,
                escape=escape,
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
        self.last_used = time.time()
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
                    msg = f"unexpected Fragment subtype {type(frag).__name__}"
                    raise RuntimeError(msg)

        pages_remaining = 0 if max_pages == 0 else num_files - max_pages

        if pages_remaining > 0:
            s = "s" if pages_remaining > 1 else ""
            frag = TextFragment(
                self,
                f"{pages_remaining} more item{s} at {self.link}",
                force=True,
                quote=False,
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
                return u == ctx.author and r.message == msg and r.emoji in {"❌", "⭕"}

            timeout = 60
            dt = format_dt(
                datetime.fromtimestamp(time.time() + timeout),  # noqa: DTZ006
                style="R",
            )
            msg = await ctx.reply(
                f"This post has {len(to_dl)} items. Are you sure? React {dt}."
                "\n-# You can post specific pages with a command like "
                "`b>post pages=1-3,5,7,12-16`",
                mention_author=True,
            )
            for emoji in "⭕❌":
                ctx.bot.shared.create_task(msg.add_reaction(emoji))

            try:
                reaction, _ = await ctx.bot.wait_for(
                    "reaction_add",
                    check=check,
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                emoji = "❌"
            else:
                emoji = reaction.emoji

            await msg.delete()
            if emoji == "❌":
                return False

        lang = settings.language_or_default()

        for item in to_trans:
            item.translate(lang)

        if self.site.concurrent:
            for item in to_dl:
                item.save()

        embedded = False

        file_batch: list[File] = []
        limit = get_size_limit(ctx)
        text_fragments: list[TextFragment] = []

        async def send_files():
            nonlocal embedded
            if file_batch:
                embedded = True
                await ctx.send(files=file_batch)
                file_batch.clear()

        async def send_text():
            for _queue, chunk in groupby(text_fragments, key=lambda f: f.queue):
                chunk = list(chunk)
                translated = [
                    await frag.translate(lang) if not frag.skip_translate else None
                    for frag in chunk
                ]

                if any(translated):
                    dim = "\n".join(line.format(diminished=True) for line in chunk)
                    content = "\n".join(
                        trans or orig.format() for orig, trans in zip(chunk, translated)
                    )
                    quote = "> " if chunk[-1].quote else ""
                    text = f"{dim}\n{quote}-# <:trans:1289284212372934737>\n{content}"
                else:
                    text = "\n".join(frag.format() for frag in chunk)

                if text:
                    if spoiler:
                        text = f"||{text}||"

                    text = INVITE_EXPR.sub(r"`discord.gg/\2`", text)

                    await ctx.send(text, suppress_embeds=True)

            text_fragments.clear()

        try:
            for item, spoiler in items:
                match type(item).__name__:
                    case "TextFragment":
                        tfrag: TextFragment = item  # type: ignore
                        if tfrag.force:
                            await send_files()
                            await ctx.send(tfrag.format(), suppress_embeds=True)
                        else:
                            text_fragments.append(tfrag)
                    case "EmbedFragment":
                        await send_files()
                        await send_text()
                        efrag: EmbedFragment = item  # type: ignore
                        await ctx.send(embed=efrag.embed)
                    case "FileFragment":
                        await send_text()
                        frag: FileFragment = item  # type: ignore
                        if to_file := getattr(frag, "to_file", None):
                            frag = await to_file(ctx)
                        await frag.save()
                        file_bytes = frag.file_bytes
                        filename = frag.filename
                        if not file_bytes:
                            msg = "frag.save failed to set file_bytes"
                            raise RuntimeError(msg)
                        if frag.pp_bytes is not None and len(frag.pp_bytes) <= limit:
                            file_bytes = frag.pp_bytes
                            filename = frag.pp_filename
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
                                    "File too large to upload "
                                    f"({display_bytes(size)}).",
                                )
                            continue
                        if len(file_batch) == 10:
                            await send_files()
                        file_batch.append(
                            File(BytesIO(file_bytes), filename, spoiler=spoiler),
                        )
                    case _:
                        msg = f"unexpected item of type {type(item).__name__}"
                        raise RuntimeError(msg)
        finally:
            await send_files()
            await send_text()

        return embedded
