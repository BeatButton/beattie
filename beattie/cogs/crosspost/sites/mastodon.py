from __future__ import annotations

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


GLOB_SITE_EXCLUDE = {
    "tenor.com",
    "giphy.com",
    "pixiv.net",
    "twitter.com",
    "fxtwitter.com",
    "vxtwitter.com",
    "sxtwitter.com",
    "zztwitter.com",
    "twxtter.com",
    "twittervx.com",
    "inkbunny.net",
    "imgur.com",
    "tumblr.com",
    "rule34.xxx",
    "hiccears.com",
    "gelbooru.com",
    "fanbox.cc",
    "discord.gg",
    "youtu.be",
    "youtube.com",
    "itch.io",
    "crepu.net",
    "x.com",
    "fixupx.com",
    "fixvx.com",
}

API_FMT = "https://{}/api/v1/statuses/{}"


class Mastodon(Site):
    name = "mastodon"
    pattern = re.compile(r"(https?://([^\s/]+)/(?:.+/)+([\w-]+))(?:[\s>/]|$)")

    auth: dict[str, dict[str, str]]

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        with open("config/crosspost/mastodon.toml") as fp:
            self.auth = toml.load(fp)

    async def handler(
        self,
        ctx: CrosspostContext,
        queue: FragmentQueue,
        link: str,
        site: str,
        post_id: str,
    ):
        info = self.cog.tldextract(link)
        if f"{info.domain}.{info.suffix}" in GLOB_SITE_EXCLUDE:
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
            return False
        if not (images := post.get("media_attachments")):
            return False

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
