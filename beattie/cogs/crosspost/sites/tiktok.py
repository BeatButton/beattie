from __future__ import annotations

import base64
import re
import urllib.parse as urlparse
from html import unescape as html_unescape
from typing import TYPE_CHECKING, TypedDict

from lxml import etree

from ..selectors import og
from .site import Site

OG_URL = og("url")
OG_VIDEO = og("video")
OG_IMAGE = og("image")
OG_IMAGE_TYPE = og("image:type")
LINK_OEMBED = './/link[@type="application/json+oembed"]'

if TYPE_CHECKING:
    from ..context import CrosspostContext
    from ..queue import FragmentQueue

    class Response(TypedDict):
        url: str


class Tiktok(Site):
    name = "tiktok"
    pattern = re.compile(
        r"https?://(?:\w+\.)*(?:vx|kk)?t[in]ktok\.com/(?:@[\w\.]+/video/|t/)?[\w\-]+",
    )

    async def handler(
        self,
        _ctx: CrosspostContext,
        queue: FragmentQueue,
        link: str,
    ):
        split = urlparse.urlsplit(link)
        link = f"https://tnktok.com{split.path}?addDesc=true"
        async with self.cog.get(
            link,
            error_for_status=False,
            follow_redirects=False,
        ) as resp:
            root = etree.fromstring(resp.content, self.cog.parser)

        try:
            queue.link = root.xpath(OG_URL)[0].get("content")
        except IndexError:
            msg = "Post not found."
            raise IndexError(msg) from None

        alt = root.xpath(LINK_OEMBED)[0].get("href")
        split = urlparse.urlsplit(urlparse.unquote(html_unescape(alt)))
        query = urlparse.parse_qs(split.query)
        queue.author = query["unique_id"][0]

        if images := root.xpath(OG_IMAGE):
            mimetypes = root.xpath(OG_IMAGE_TYPE)
            post_id = images[0].get("content").rpartition("/")[2]
            for idx, (image, mimetype) in enumerate(
                zip(images, mimetypes, strict=True),
                1,
            ):
                ext = mimetype.get("content").rpartition("/")[2]
                filename = f"{post_id}_{idx}.{ext}"
                queue.push_file(image.get("content"), filename=filename)
        else:
            url = root.xpath(OG_VIDEO)[0].get("content")
            queue.push_file(url)

        if encoded := query.get("description"):
            text = base64.b64decode(encoded[0]).decode("utf-8")
            queue.push_text(text)
