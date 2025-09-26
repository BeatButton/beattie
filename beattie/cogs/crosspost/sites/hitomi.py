from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, TypedDict

from .site import Site

if TYPE_CHECKING:

    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class File(TypedDict):
        name: str
        hash: str

    class Response(TypedDict):
        title: str
        galleryurl: str
        files: list[File]


NETLOC = "gold-usergeneratedcontent.net"
GG_JS = f"https://ltn.{NETLOC}/gg.js"
GG_CASE = re.compile(r"case (\d+):(?:\no = (\d+))?")
GG_DEFAULT = re.compile(r"var o = (\d+)")
GG_B = re.compile(r"b: '(\d+)/'")


class Hitomi(Site):
    name = "hitomi"
    pattern = re.compile(
        r"https?://(?:www\.)?hitomi\.la/(?:[^/]+)/(?:[\w-]+-)?(\d+)(?:\.html)?",
    )
    concurrent = False

    async def load(self) -> None:
        async with self.cog.get(GG_JS) as resp:
            text = resp.text

        gg_map: dict[int, int] = {}
        cases: list[int] = []
        for m in GG_CASE.finditer(text):
            case = int(m[1])
            cases.append(case)
            if o := m[2]:
                o = int(o)
                for case in cases:
                    gg_map[case] = o
                cases.clear()

        dm = GG_DEFAULT.search(text)
        if dm is None:
            default = 0
        else:
            default = int(dm[1])

        bm = GG_B.search(text)
        if bm is None:
            b = ""
        else:
            b = bm[1]

        self.gg_map = gg_map
        self.gg_default = default
        self.gg_b = b

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        gallery_id: str,
    ):
        url = f"https://ltn.{NETLOC}/galleries/{gallery_id}.js"
        async with self.cog.get(url) as resp:
            text = resp.text
        data: Response = json.loads(text.rpartition("=")[2])

        refer = {"Referer": f"https://hitomi.la{data["galleryurl"]}"}

        for file in data["files"]:
            fh = file["hash"]
            n = int(f"{fh[-1]}{fh[-3:-1]}", 16)
            gg = self.gg_map.get(n, self.gg_default) + 1
            url = f"https://w{gg}.{NETLOC}/{self.gg_b}/{n}/{fh}.webp"
            queue.push_file(url, headers=refer)

        queue.push_text(data["title"], bold=True)
