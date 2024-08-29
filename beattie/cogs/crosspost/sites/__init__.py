from __future__ import annotations

from typing import Type

from .site import Site

from .twitter import Twitter
from .pixiv import Pixiv
from .hiccears import Hiccears
from .tumblr import Tumblr
from .mastodon import Mastodon
from .inkbunny import Inkbunny
from .imgur import Imgur
from .gelbooru import Gelbooru
from .rule34 import Rule34
from .fanbox import Fanbox
from .lofter import Lofter
from .misskey import Misskey
from .poipiku import Poipiku
from .bluesky import Bluesky
from .paheal import Paheal
from .furaffinity import FurAffinity
from .ygallery import YGallery
from .pillowfort import Pillowfort
from .yt_community import YTCommunity
from .e621 import E621
from .exhentai import Exhentai
from .tiktok import Tiktok

SITES: list[Type[Site]] = [
    Twitter,
    Pixiv,
    Hiccears,
    Tumblr,
    Mastodon,
    Inkbunny,
    Imgur,
    Gelbooru,
    Rule34,
    Fanbox,
    Lofter,
    Misskey,
    Poipiku,
    Bluesky,
    Paheal,
    FurAffinity,
    YGallery,
    Pillowfort,
    YTCommunity,
    E621,
    Exhentai,
    Tiktok,
]
