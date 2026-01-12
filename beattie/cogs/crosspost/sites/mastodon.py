from __future__ import annotations

import json
import logging
import re
import urllib.parse as urlparse
from typing import TYPE_CHECKING, Any, Literal, TypedDict

import toml
from lxml import html

from beattie.utils.aioutils import adump
from beattie.utils.exceptions import ResponseError

from ..postprocess import ffmpeg_gif_pp
from .site import Site

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class Link(TypedDict):
        rel: str
        href: str

    class WellKnown(TypedDict):
        links: list[Link]

    class Software(TypedDict):
        name: str

    class NodeInfo(TypedDict):
        software: Software

    class MastodonAccount(TypedDict):
        url: str

    class MastodonMedia(TypedDict):
        type: str
        url: str
        preview_url: str
        remote_url: str | None

    class MastodonResponse(TypedDict):
        spoiler_text: str
        url: str
        visibility: str
        content: str
        account: MastodonAccount
        media_attachments: list[MastodonMedia]

    class MisskeyUser(TypedDict):
        id: str

    class MisskeyFile(TypedDict):
        name: str
        type: str
        url: str
        thumbnailUrl: str

    class MisskeyResponse(TypedDict):
        user: MisskeyUser
        text: str
        files: list[MisskeyFile]

    class PeertubeAccount(TypedDict):
        url: str

    class PeertubePlaylistFile(TypedDict):
        width: int
        fileDownloadUrl: str

    class PeertubePlaylist(TypedDict):
        files: list[PeertubePlaylistFile]

    class PeertubeResponse(TypedDict):
        name: str
        description: str
        isLive: bool
        account: PeertubeAccount
        streamingPlaylists: list[PeertubePlaylist]

    Handler = Callable[
        [CrosspostContext, FragmentQueue, str, str, str, dict[str, str]],
        Coroutine[Any, Any, None],
    ]


MASTO_API_FMT = "https://{}/api/v1/statuses/{}"
PEERTUBE_API_FMT = "https://{}/api/v1/videos/{}"
MISSKEY_API_FMT = "https://{}/api/notes/show"
CONFIG = "config/crosspost/mastodon.toml"


class Mastodon(Site):
    name = "mastodon"
    pattern = re.compile(r"(https?://([^\s/]+)/(?:\S+/)+([\w-]+))(?:[\s>/]|$)")

    auth: dict[str, dict[str, str]]
    whitelist: dict[str, str]
    blacklist: set[str]
    dispatch: dict[str, Handler | Literal["SKIP"]]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        self.logger = logging.getLogger(__name__)
        try:
            with open(CONFIG) as fp:
                data = toml.load(fp)
        except FileNotFoundError:
            data = {}

        self.whitelist = data.pop("whitelist", {})
        self.blacklist = set(data.pop("blacklist", []))
        self.auth = data

        pre = "do_"
        self.dispatch = {
            name.removeprefix(pre): getattr(self, name)
            for name in dir(self)
            if name.startswith(pre)
        }
        self.dispatch["sharkey"] = self.do_misskey
        self.dispatch["iceshrimp"] = self.do_misskey
        self.dispatch["pleroma"] = self.do_mastodon
        self.dispatch["akkoma"] = self.do_mastodon
        self.dispatch["bridgy-fed"] = "SKIP"

    async def sniff(self, domain: str) -> str:
        async with self.cog.get(
            f"https://{domain}/.well-known/nodeinfo",
        ) as resp:
            info: WellKnown = resp.json()

        link = info["links"][0]["href"]

        async with self.cog.get(link) as resp:
            data: NodeInfo = resp.json()

        return data["software"]["name"]

    async def determine(self, domain: str) -> str | None:
        try:
            software = await self.sniff(domain)
        except (
            ResponseError,
            json.JSONDecodeError,
            IndexError,
        ):
            software = None

        if software:
            self.logger.info("detected %s as activitypub (%s)", domain, software)
            try:
                self.blacklist.remove(domain)
            except KeyError:
                pass
            self.whitelist[domain] = software
        else:
            self.logger.info("failed to detect %s as activitypub", domain)
            self.whitelist.pop(domain, None)
            self.blacklist.add(domain)

        data = {**self.auth, "whitelist": self.whitelist, "blacklist": self.blacklist}

        await adump(CONFIG, data)

        return software

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        link: str,
        site: str,
        post_id: str,
    ):
        info = await self.cog.tldextract(link)
        domain = f"{info.domain}.{info.suffix}"
        if sub := info.subdomain:
            domain = f"{sub}.{domain}"
        if domain in self.blacklist:
            return
        if (software := self.whitelist.get(domain)) is None and (
            software := await self.determine(domain)
        ) is None:
            return

        if (handler := self.dispatch.get(software)) is None:
            msg = f"unsupported activitypub software {software}"
            raise RuntimeError(msg)

        if handler == "SKIP":
            return

        headers = {"Accept": "application/json"}

        if auth := self.auth.get(site):
            headers["Authorization"] = f"Bearer {auth['token']}"

        await handler(ctx, queue, link, site, post_id, headers)

    async def do_mastodon(
        self,
        ctx: CrosspostContext,  # noqa: ARG002
        queue: FragmentQueue,
        link: str,  # noqa: ARG002
        site: str,
        post_id: str,
        headers: dict[str, str],
    ):
        api_url = MASTO_API_FMT.format(site, post_id)

        async with self.cog.get(api_url, headers=headers) as resp:
            post: MastodonResponse = resp.json()

        images = post["media_attachments"]

        if not images:
            return

        if post["visibility"] not in ("public", "unlisted"):
            return

        queue.author = post["account"]["url"]

        for image in images:
            urls = [url for url in [image["remote_url"], image["url"]] if url]

            for idx, url in enumerate(urls):
                if not urlparse.urlparse(url).netloc:
                    netloc = urlparse.urlparse(str(resp.url)).netloc
                    urls[idx] = f"https://{netloc}/{url.lstrip('/')}"
            if image["type"] == "gifv":
                queue.push_file(*urls, postprocess=ffmpeg_gif_pp)
            else:
                queue.push_file(*urls)

        if content := post["content"]:
            if cw := post["spoiler_text"]:
                queue.push_text(cw, skip_translate=True, diminished=True)

            fragments = html.fragments_fromstring(
                re.sub(r"<br ?/?>", "\n", content),
                parser=self.cog.parser,
            )
            text = "\n".join(
                f if isinstance(f, str) else f.text_content() for f in fragments
            )
            queue.push_text(text)

    async def do_misskey(
        self,
        ctx: CrosspostContext,  # noqa: ARG002
        queue: FragmentQueue,
        link: str,  # noqa: ARG002
        site: str,
        post_id: str,
        headers: dict[str, str],
    ):
        url = MISSKEY_API_FMT.format(site)
        body = json.dumps({"noteId": post_id}).encode("utf-8")

        async with self.cog.get(
            url,
            method="POST",
            data=body,
            headers={**headers, "Content-Type": "application/json"},
        ) as resp:
            data: MisskeyResponse = resp.json()

        if not (files := data["files"]):
            return

        queue.author = data["user"]["id"]

        for file in files:
            pp = None
            if file["type"] == "image/apng":
                pp = ffmpeg_gif_pp
            queue.push_file(file["url"], filename=file["name"], postprocess=pp)

        if text := data["text"]:
            queue.push_text(text)

    async def do_peertube(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        _link: str,
        site: str,
        post_id: str,
        headers: dict[str, str],
    ):
        api_url = PEERTUBE_API_FMT.format(site, post_id)

        async with self.cog.get(api_url, headers=headers) as resp:
            post: PeertubeResponse = resp.json()
        if post["isLive"]:
            return

        if not (playlists := post["streamingPlaylists"]):
            return

        queue.author = post["account"]["url"]

        for playlist in playlists:
            if not (files := playlist["files"]):
                continue

            file = max(files, key=lambda f: f["width"])
            queue.push_file(file["fileDownloadUrl"])

        queue.push_text(post["name"], bold=True)
        queue.push_text(post["description"])
