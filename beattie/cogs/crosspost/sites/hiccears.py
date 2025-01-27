from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

import niquests
import niquests.cookies
import toml
from lxml import html

from .site import Site

if TYPE_CHECKING:
    from ..cog import Crosspost
    from ..context import CrosspostContext
    from ..queue import FragmentQueue


TEXT_TRIM = re.compile(r" ?https://t\.co/\w+$")
VIDEO_WIDTH = re.compile(r"vid/(\d+)x")


IMG_SELECTOR = ".//a[contains(@href, 'imgs')]"
THUMB_SELECTOR = ".//a[contains(@class, 'photo-preview')]"
TEXT_SELECTOR = ".//div[contains(@class, 'widget-box-content')]"
TITLE_SELECTOR = ".//h2[contains(@class, 'section-title')]"
AUTHOR_SELECTOR = ".//p[contains(@class, 'section-pretitle')]"
NEXT_SELECTOR = ".//a[contains(@class, 'right')]"


class Hiccears(Site):
    name = "hiccears"
    pattern = re.compile(
        r"https?://(?:www\.)?hiccears\.com/(?:[\w-]+/)?"
        r"(?:contents/[\w-]+|file/[\w-]+/[\w-]+/preview)"
    )

    headers: dict[str, str] = {}

    def __init__(self, cog: Crosspost):
        super().__init__(cog)
        self.logger = logging.getLogger(__name__)

    async def load(self):
        with open("config/crosspost/hiccears.toml") as fp:
            self.headers = toml.load(fp)

    async def handler(self, ctx: CrosspostContext, queue: FragmentQueue, link: str):
        async with self.cog.get(
            link, headers=self.headers, use_browser_ua=True
        ) as resp:
            self.update_hiccears_cookies(resp)
            root = html.document_fromstring(await resp.content or b"", self.cog.parser)

        if author := root.xpath(AUTHOR_SELECTOR):
            queue.author = author[0].text_content().strip()

        if link.endswith("preview"):
            queue.push_file(
                re.sub(
                    r"preview(/\d+)?",
                    "download",
                    link,
                ),
                headers=self.headers,
            )
        else:
            while True:
                thumbs = root.xpath(THUMB_SELECTOR)

                for thumb in thumbs:
                    href = f"https://{resp.host}{thumb.get('href')}"
                    queue.push_file(
                        re.sub(
                            r"preview(/\d+)?",
                            "download",
                            href,
                        ),
                        headers=self.headers,
                    )

                if next_page := root.xpath(NEXT_SELECTOR):
                    next_url = f"https://{resp.host}{next_page[0].get('href')}"
                    async with self.cog.get(
                        next_url, headers=self.headers, use_browser_ua=True
                    ) as resp:
                        self.update_hiccears_cookies(resp)
                        root = html.document_fromstring(
                            await resp.content or b"",
                            self.cog.parser,
                        )
                else:
                    break

        if title := root.xpath(TITLE_SELECTOR):
            queue.push_text(title[0].text, bold=True)
        if elem := root.xpath(TEXT_SELECTOR):
            description = elem[0].text_content().strip()
            description = description.removeprefix("Description")
            description = re.sub(r"\r?\n\t+", "", description)
            if description:
                queue.push_text(description)

    def update_hiccears_cookies(self, resp: niquests.AsyncResponse):
        assert isinstance(resp.cookies, niquests.cookies.RequestsCookieJar)
        if sess := resp.cookies.get("hiccears"):
            self.logger.info("Refreshing cookies from response")

            cookie = re.sub(
                r"hiccears=\w+;REMEMBERME=(.*)",
                rf"hiccears={sess};REMEMBERME=\g<1>",
                self.headers["Cookie"],
            )

            self.headers["Cookie"] = cookie

            with open("config/crosspost/hiccears.toml", "w") as fp:
                toml.dump(self.headers, fp)
