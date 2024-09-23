from __future__ import annotations

import json
import logging
import re
import urllib.parse as urlparse
from typing import TYPE_CHECKING

import aiohttp
from lxml import html
import toml

from beattie.utils.exceptions import ResponseError

from ..postprocess import ffmpeg_gif_pp
from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


API_FMT = "https://{}/api/v1/statuses/{}"
CONFIG = "config/crosspost/mastodon.toml"


class Mastodon(Site):
    name = "mastodon"
    pattern = re.compile(r"(https?://([^\s/]+)/(?:\S+/)+([\w-]+))(?:[\s>/]|$)")

    auth: dict[str, dict[str, str]]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        self.logger = logging.getLogger(__name__)
        with open(CONFIG) as fp:
            data = toml.load(fp)

        self.whitelist = set(data.pop("whitelist", []))
        self.blacklist = set(data.pop("blacklist", []))
        self.auth = data

    async def sniff(self, domain: str) -> bool:
        async with self.cog.get(
            f"https://{domain}/.well-known/nodeinfo",
            use_default_headers=False,
        ) as resp:
            data = await resp.json()

        link = data["links"][0]["href"]

        async with self.cog.get(link, use_default_headers=False) as resp:
            data = await resp.json()

        return "activitypub" in data["protocols"]

    async def determine(self, domain: str) -> bool:
        try:
            supports = await self.sniff(domain)
        except (ResponseError, json.JSONDecodeError, IndexError):
            supports = False
        if supports:
            self.logger.info(f"detected {domain} as activitypub")
            try:
                self.blacklist.remove(domain)
            except KeyError:
                pass
            self.whitelist.add(domain)
        else:
            self.logger.info(f"failed to detect {domain} as activitypub")
            try:
                self.whitelist.remove(domain)
            except KeyError:
                pass
            self.blacklist.add(domain)

        data = {**self.auth, "whitelist": self.whitelist, "blacklist": self.blacklist}

        with open(CONFIG, "w") as fp:
            toml.dump(data, fp)

        return supports

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        link: str,
        site: str,
        post_id: str,
    ):
        info = self.cog.tldextract(link)
        domain = f"{info.domain}.{info.suffix}"
        if domain in self.blacklist:
            return False
        if domain not in self.whitelist:
            if not await self.determine(domain):
                return False

        if auth := self.auth.get(site):
            headers = {"Authorization": f"Bearer {auth['token']}"}
        else:
            headers = {}

        api_url = API_FMT.format(site, post_id)
        try:
            async with self.cog.get(
                api_url, headers=headers, use_default_headers=False
            ) as resp:
                post = await resp.json()
        except (ResponseError, aiohttp.ClientError):
            self.logger.info(f"not a mastodon instance: {domain}")
            return False
        if not (images := post.get("media_attachments")):
            return False

        queue.author = post["account"]["url"]

        real_url = post["url"]
        queue.link = real_url
        if real_url.casefold() != link.casefold():
            queue.push_text(real_url)

        for image in images:
            urls = [url for url in [image["remote_url"], image["url"]] if url]

            for idx, url in enumerate(urls):
                if not urlparse.urlparse(url).netloc:
                    netloc = urlparse.urlparse(str(resp.url)).netloc
                    urls[idx] = f"https://{netloc}/{url.lstrip('/')}"
            if image.get("type") == "gifv":
                filename = (
                    f"{str(resp.url).rpartition('/')[2].removesuffix('.mp4')}.gif"
                )
                queue.push_file(*urls, filename=filename, postprocess=ffmpeg_gif_pp)
            else:
                queue.push_file(*urls)

        if content := post["content"]:
            if cw := post.get("spoiler_text"):
                queue.push_text(cw)

            fragments = html.fragments_fromstring(
                re.sub(r"<br ?/?>", "\n", content), parser=self.cog.parser
            )
            text = "\n".join(
                f if isinstance(f, str) else f.text_content() for f in fragments
            )
            queue.push_text(f">>> {text}")
