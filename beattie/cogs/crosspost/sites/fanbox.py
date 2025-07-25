from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.parse
from typing import TYPE_CHECKING, Any

import httpx
import toml
from lxml import etree

from .site import Site

if TYPE_CHECKING:
    from types import TracebackType

    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


class Fanbox(Site):
    name = "fanbox"
    pattern = re.compile(
        r"https://(?:(?:www\.)?fanbox\.cc/@)?([\w-]+)(?:\.fanbox\.cc)?/posts/(\d+)",
    )
    solver_url: str
    proxy_url: str

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        try:
            with open("config/crosspost/fanbox.toml") as fp:
                data = toml.load(fp)
                self.solver_url = data["solver"]
                self.proxy_url = data["proxy"]
        except (FileNotFoundError, KeyError):
            logging.getLogger(__name__).warning(
                "no solver/proxy setup found, fanbox disabled.",
            )
            self.cog.sites.remove(self)

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        user: str,
        post_id: str,
    ):
        queue.link = f"https://www.fanbox.cc/@{user}/posts/{post_id}"
        url = f"https://api.fanbox.cc/post.info?postId={post_id}"

        async with FlareSolverr(self.solver_url, self.proxy_url) as fs:
            solve = asyncio.create_task(fs.get("https://fanbox.cc"))
            send = asyncio.create_task(ctx.send("Solving challenge..."))
            try:
                await solve
                resp = await fs.get(
                    url,
                    headers={
                        "Accept": "application/json, text/plain, */*",
                        "Origin": "https://www.fanbox.cc",
                    },
                )
            finally:
                msg = await send
                await msg.delete()

        root = etree.fromstring(resp["solution"]["response"], self.cog.parser)
        data = json.loads(root.xpath("//pre")[0].text)

        post = data["body"]
        body = post["body"]
        if body is None:
            return

        queue.author = post["creatorId"]
        headers = {"Referer": queue.link}

        match post["type"]:
            case "image":
                for image in body["images"]:
                    queue.push_fallback(
                        image["originalUrl"],
                        image["thumbnailUrl"],
                        headers,
                    )
                if text := body.get("text", "").strip():
                    queue.push_text(text, interlaced=True)
            case "file":
                for file_info in body["files"]:
                    url = file_info["url"]
                    filename = file_info["name"] + "." + file_info["extension"]
                    queue.push_file(url, filename=filename)
                if text := body.get("text", "").strip():
                    queue.push_text(text, interlaced=True)
            case "article":
                blocks = body["blocks"]
                image_map = body["imageMap"]
                file_map = body["fileMap"]

                if not (image_map or file_map):
                    return

                for block in blocks:
                    match block["type"]:
                        case "p":
                            if text := block.get("text", "").strip():
                                queue.push_text(text, interlaced=True)
                        case "image":
                            image = image_map[block["imageId"]]
                            queue.push_fallback(
                                image["originalUrl"],
                                image["thumbnailUrl"],
                                headers,
                            )
                        case "file":
                            queue.push_file(file_map[block["fileId"]]["url"])
            case other:
                msg = f"Unrecognized post type {other}!"
                raise RuntimeError(msg)


class FlareSolverr:
    solver: str
    proxy: str
    session: str | None
    client: httpx.AsyncClient

    def __init__(self, solver: str, proxy: str):
        self.solver = solver
        self.proxy = proxy
        self.client = httpx.AsyncClient(follow_redirects=True, timeout=None)
        self.session = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ):
        await self.close()

    async def start(self):
        if self.session is None:
            data = await self._request(
                {"cmd": "sessions.create", "proxy": {"url": self.proxy}},
            )
            self.session = data["session"]

    async def close(self):
        if self.session is not None:
            await self._request({"cmd": "sessions.destroy", "session": self.session})
            self.session = None

    async def _request(self, command: dict[str, Any]) -> dict[str, Any]:
        resp = await self.client.post(
            self.solver,
            headers={"Content-Type": "application/json"},
            content=json.dumps(command),
        )
        data = resp.json()
        if data["status"] != "ok":
            msg = f"solver error: {data['message']}"
            raise RuntimeError(msg)

        return data

    async def get(self, url: str, *, headers: dict[str, str] = None) -> dict[str, Any]:
        if headers:
            for name, value in headers.items():
                slug = f"{name}:{value}"
                data = urllib.parse.quote(slug, safe="")
                url = f"{url}&$$headers[]={data}"
        return await self._request(
            {
                "cmd": "request.get",
                "url": url,
                "session": self.session,
            },
        )
