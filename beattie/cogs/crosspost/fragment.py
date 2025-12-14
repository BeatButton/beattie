from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from sys import getsizeof
from typing import TYPE_CHECKING, Any, NamedTuple

from discord.utils import escape_markdown

from beattie.utils.etc import URL_EXPR, get_size_limit, replace_ext

from .database_types import TextLength
from .postprocess import magick_png_pp
from .translator import DONT, Language

if TYPE_CHECKING:
    from collections.abc import Awaitable

    from discord import Embed

    from .cog import Crosspost
    from .context import CrosspostContext
    from .postprocess import PP
    from .queue import FragmentQueue

FILE_CHAR = r"[\w. [\]-]"
FILENAME_EXPR = re.compile(rf"{FILE_CHAR}+\.{FILE_CHAR}+")


class Fragment:
    queue: FragmentQueue

    def __init__(self, queue: FragmentQueue):
        self.queue = queue

    @property
    def cog(self) -> Crosspost:
        return self.queue.cog

    def __sizeof__(self) -> int:
        return super().__sizeof__() + sum(
            getsizeof(getattr(self, name))
            for name in getattr(self, "__annotations__", {})
            if name != "queue"
        )


class FileFragment(Fragment):
    urls: tuple[str, ...]
    headers: dict[str, str] | None
    use_browser_ua: bool
    filename: str
    file_bytes: bytes
    pp_filename: str | None
    pp_bytes: bytes | None
    dl_task: asyncio.Task[None] | None
    postprocess: PP | None
    pp_extra: Any
    lock_filename: bool
    can_link: bool

    def __init__(
        self,
        queue: FragmentQueue,
        *urls: str,
        filename: str = None,
        headers: dict[str, str] = None,
        use_browser_ua: bool = False,
        postprocess: PP = None,
        pp_extra: Any = None,
        lock_filename: bool = False,
        can_link: bool = True,
    ):
        super().__init__(queue)
        self.urls = urls
        self.postprocess = postprocess
        self.pp_extra = pp_extra
        self.pp_filename = None
        self.pp_bytes = None
        self.headers = headers
        self.use_browser_ua = use_browser_ua
        self.lock_filename = lock_filename
        self.can_link = can_link

        if filename is None:
            for url in urls:
                if matches := FILENAME_EXPR.findall(url):
                    filename = matches[-1]
        if filename is None:
            msg = f"could not parse filename from URL: {urls[0]}"
            raise RuntimeError(msg)
        for ext, sub in [
            ("jfif", "jpeg"),
            ("pnj", "png"),
        ]:
            if filename.endswith(f".{ext}"):
                filename = replace_ext(filename, sub)
                break
        if postprocess is None and any(
            filename.endswith(f".{ext}") for ext in ["webp", "avif"]
        ):
            self.postprocess = magick_png_pp
        self.filename = filename

        self.file_bytes = b""
        self.dl_task = None

    def save(self) -> Awaitable[None]:
        if self.dl_task is None:
            self.dl_task = asyncio.Task(self._save())
        return self.dl_task

    async def _save(self):
        file_bytes, filename = await self.cog.save(
            *self.urls,
            headers=self.headers,
            use_browser_ua=self.use_browser_ua,
        )

        if not self.lock_filename and filename is not None:
            self.filename = filename

        self.file_bytes = file_bytes

        if self.postprocess is not None:
            await self.postprocess(self)


class FileSpec(NamedTuple):
    url: str
    filename: str | None = None
    postprocess: PP | None = None
    pp_extra: Any = None


@dataclass
class FallbackCandidate:
    url: str
    filename: str | None
    postprocess: PP | None
    pp_extra: PP | None
    fragment: FileFragment | None = None


class FallbackFragment(Fragment):
    headers: dict[str, str] | None
    length_tasks: dict[int, asyncio.Task[int]]
    candidates: list[FallbackCandidate]

    def __init__(
        self,
        queue: FragmentQueue,
        *file_specs: FileSpec,
        headers: dict[str, str] = None,
    ):
        super().__init__(queue)
        self.headers = headers
        self.length_tasks = {}
        self.candidates = [
            FallbackCandidate(fs.url, fs.filename, fs.postprocess, fs.pp_extra)
            for fs in file_specs
        ]

    async def _determine_length(self, idx: int) -> int:
        candidate = self.candidates[idx]
        candidate.fragment = frag = FileFragment(
            self.queue,
            candidate.url,
            filename=candidate.filename,
            headers=self.headers,
            postprocess=candidate.postprocess,
            pp_extra=candidate.pp_extra,
        )
        await frag.save()
        if (pp_bytes := frag.pp_bytes) is not None:
            length = len(pp_bytes)
        else:
            length = len(frag.file_bytes)

        return length

    async def determine_length(self, idx: int) -> int:
        if (task := self.length_tasks.get(idx)) is None:
            task = asyncio.create_task(self._determine_length(idx))
            self.length_tasks[idx] = task
        return await task

    async def to_file(self, ctx: CrosspostContext) -> FileFragment:
        for idx, candidate in enumerate(self.candidates):
            length = await self.determine_length(idx)
            if get_size_limit(ctx) > length:
                if (frag := candidate.fragment) is None:
                    candidate.fragment = frag = FileFragment(
                        self.queue,
                        candidate.url,
                        filename=candidate.filename,
                        headers=self.headers,
                    )
                return frag

        candidate = self.candidates[0]
        if (frag := candidate.fragment) is None:
            candidate.fragment = frag = FileFragment(
                self.queue,
                candidate.url,
                filename=candidate.filename,
                headers=self.headers,
            )

        return frag


class EmbedFragment(Fragment):
    embed: Embed

    def __init__(self, queue: FragmentQueue, embed: Embed):
        super().__init__(queue)
        self.embed = embed


class TextFragment(Fragment):
    content: str
    length: TextLength
    force: bool
    skip_translate: bool
    interlaced: bool
    bold: bool
    italic: bool
    quote: bool
    diminished: bool
    dt_task: asyncio.Task[Language] | None
    trans_tasks: dict[Language, asyncio.Task[str | None]]

    def __init__(
        self,
        queue: FragmentQueue,
        content: str,
        *,
        length: TextLength = TextLength.SHORT,
        force: bool = False,
        interlaced: bool = False,
        skip_translate: bool = None,
        bold: bool = False,
        italic: bool = False,
        quote: bool = True,
        diminished: bool = False,
        escape: bool = True,
    ):
        super().__init__(queue)
        self.content = content
        self.length = length
        self.force = force
        if skip_translate is not None:
            self.skip_translate = skip_translate
        else:
            self.skip_translate = force
        self.interlaced = interlaced
        self.bold = bold
        self.italic = italic
        self.quote = quote
        self.diminished = diminished
        self.escape = escape
        self.dt_task = None
        self.trans_tasks = {}

    def __str__(self) -> str:
        return self.content

    def format(
        self,
        text: str = None,
        *,
        bold: bool = None,
        italic: bool = None,
        diminished: bool = None,
        quote: bool = None,
        escape: bool = None,
    ) -> str:
        if text is None:
            text = self.content
        if bold is None:
            bold = self.bold
        if italic is None:
            italic = self.italic
        if diminished is None:
            diminished = self.diminished
        if quote is None:
            quote = self.quote
        if escape is None:
            escape = self.escape

        if escape:
            text = escape_markdown(text)

        if bold:
            text = f"**{text}**"
        if italic:
            text = f"*{text}*"
        if diminished:
            text = "\n".join(
                f"-# {line}" if line.strip() else "\N{ZERO WIDTH SPACE}"
                for line in text.splitlines()
            )
        if quote:
            text = "\n".join(
                f"> {line}" if line.strip() else "> \N{ZERO WIDTH SPACE}"
                for line in text.splitlines()
            )

        return text

    def detect(self) -> Awaitable[Language]:
        if self.dt_task is None:
            if translator := self.cog.translator:
                self.dt_task = asyncio.Task(translator.detect(self.content))
            else:
                self.dt_task = asyncio.Task(asyncio.sleep(0, DONT))
        return self.dt_task

    async def _translate(self, target: Language) -> str | None:
        if (translator := self.cog.translator) is None:
            return None

        if target == DONT:
            return None

        source = await self.detect()
        if source in (DONT, target):
            return None

        content = URL_EXPR.sub("", self.content).strip()

        if not content:
            return None

        trans = (
            await translator.translate(
                content,
                source.code,
                target.code,
            )
        ).strip()

        if not trans or content == trans:
            return None

        return self.format(trans)

    def translate(self, target: Language) -> Awaitable[str | None]:
        if (task := self.trans_tasks.get(target)) is None:
            self.trans_tasks[target] = task = asyncio.Task(self._translate(target))

        return task
