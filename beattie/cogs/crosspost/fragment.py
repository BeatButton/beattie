from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable
from sys import getsizeof
from typing import TYPE_CHECKING, Any

from discord import Embed

from beattie.utils.etc import get_size_limit
from .translator import Language, DONT

if TYPE_CHECKING:
    from .cog import Crosspost
    from .context import CrosspostContext
    from .postprocess import PP


class Fragment:
    def __sizeof__(self) -> int:
        return super().__sizeof__() + sum(
            getsizeof(getattr(self, name))
            for name in getattr(self, "__annotations__", {})
        )


class FileFragment(Fragment):
    cog: Crosspost
    urls: tuple[str, ...]
    headers: dict[str, str] | None
    use_default_headers: bool
    filename: str
    file_bytes: bytes
    dl_task: asyncio.Task | None
    postprocess: PP | None
    pp_extra: Any
    lock_filename: bool
    can_link: bool

    def __init__(
        self,
        cog: Crosspost,
        *urls: str,
        filename: str = None,
        headers: dict[str, str] = None,
        use_default_headers: bool = False,
        postprocess: PP = None,
        pp_extra: Any = None,
        lock_filename: bool = False,
        can_link: bool = True,
    ):
        self.cog = cog
        self.urls = urls
        self.postprocess = postprocess
        self.pp_extra = pp_extra
        self.headers = headers
        self.use_default_headers = use_default_headers
        self.lock_filename = lock_filename
        self.can_link = can_link

        if filename is None:
            filename = re.findall(r"[\w. -]+\.[\w. -]+", urls[0])[-1]
        if filename is None:
            raise RuntimeError(f"could not parse filename from URL: {urls[0]}")
        for ext, sub in [
            ("jfif", "jpeg"),
            ("pnj", "png"),
        ]:
            if filename.endswith(f".{ext}"):
                filename = f"{filename.removesuffix(ext)}{sub}"
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
            use_default_headers=self.use_default_headers,
        )

        if not self.lock_filename and filename is not None:
            self.filename = filename

        if self.postprocess is not None:
            file_bytes = await self.postprocess(self, file_bytes, self.pp_extra)

        self.file_bytes = file_bytes


class FallbackFragment(Fragment):
    preferred_url: str
    fallback_url: str
    headers: dict[str, str] | None
    preferred_len: int | None
    preferred_frag: FileFragment | None
    fallback_frag: FileFragment | None

    def __init__(
        self,
        cog: Crosspost,
        preferred_url: str,
        fallback_url: str,
        headers: dict[str, str] | None,
    ):
        self.cog = cog
        self.preferred_url = preferred_url
        self.fallback_url = fallback_url
        self.headers = headers

        self.preferred_frag = None
        self.fallback_frag = None
        self.preferred_len = None

    async def to_file(self, ctx: CrosspostContext) -> FileFragment:
        if self.preferred_len is None:
            async with self.cog.get(
                self.preferred_url,
                "HEAD",
                use_default_headers=False,
                headers=self.headers,
            ) as resp:
                self.preferred_len = resp.content_length

        if self.preferred_len is not None and get_size_limit(ctx) > self.preferred_len:
            if (frag := self.preferred_frag) is None:
                frag = self.preferred_frag = FileFragment(
                    self.cog,
                    self.preferred_url,
                    headers=self.headers,
                    use_default_headers=False,
                )
        else:
            if (frag := self.fallback_frag) is None:
                frag = self.fallback_frag = FileFragment(
                    self.cog,
                    self.fallback_url,
                    headers=self.headers,
                    use_default_headers=False,
                )

        return frag


class EmbedFragment(Fragment):
    embed: Embed

    def __init__(self, embed: Embed):
        self.embed = embed


class TextFragment(Fragment):
    translations: dict[tuple[str, str], str]
    dt_task: asyncio.Task | None
    trans_tasks: dict[Language, asyncio.Task]

    def __init__(
        self,
        cog: Crosspost,
        content: str,
        force: bool = False,
        interlaced: bool = False,
        bold: bool = False,
        italic: bool = False,
        quote: bool = False,
    ):
        self.cog = cog
        self.content = content
        self.force = force
        self.interlaced = interlaced
        self.bold = bold
        self.italic = italic
        self.quote = quote
        self.dt_task = None
        self.trans_tasks = {}

    def __str__(self) -> str:
        return self.content

    def format(self, text: str = None) -> str:
        if text is None:
            text = self.content
        if self.bold:
            text = f"**{text}**"
        if self.italic:
            text = f"*{text}*"
        if self.quote:
            text = "\n".join(f"> {line}" for line in text.splitlines())

        return text

    def detect(self) -> Awaitable[Language]:
        if self.dt_task is None:
            self.dt_task = asyncio.Task(self.cog.translator.detect(self.content))
        return self.dt_task

    async def _translate(self, target: Language) -> str:
        if target == DONT:
            return self.format()

        source = await self.detect()
        if source == DONT or target == source:
            return self.format()

        trans = await self.cog.translator.translate(
            self.content,
            source.code,
            target.code,
        )

        if not trans.strip() or self.content == trans:
            return self.format()

        content = "\n".join(
            f"-# {line}" if line.strip() else "" for line in self.content.splitlines()
        )
        return self.format(f"{content}\n-# <:trans:1289284212372934737>\n{trans}")

    def translate(self, target: Language) -> Awaitable[str]:
        if (task := self.trans_tasks.get(target)) is None:
            self.trans_tasks[target] = task = asyncio.Task(self._translate(target))

        return task
