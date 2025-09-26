from __future__ import annotations

from .bluesky import Bluesky
from .danbooru import Danbooru
from .e621 import E621
from .exhentai import Exhentai
from .fanbox import Fanbox
from .furaffinity import FurAffinity
from .gelbooru import Gelbooru
from .hiccears import Hiccears
from .hitomi import Hitomi
from .imgur import Imgur
from .inkbunny import Inkbunny
from .itaku import Itaku
from .lofter import Lofter
from .mastodon import Mastodon
from .nhentai import Nhentai
from .paheal import Paheal
from .pillowfort import Pillowfort
from .pixiv import Pixiv
from .poipiku import Poipiku
from .rule34 import Rule34
from .site import Site
from .tiktok import Tiktok
from .tumblr import Tumblr
from .twitter import Twitter
from .ygallery import YGallery
from .yt_community import YTCommunity

__all__ = ["SITES", "Site"]

SITES: list[type[Site]] = [
    Bluesky,
    Danbooru,
    E621,
    Exhentai,
    Fanbox,
    FurAffinity,
    Gelbooru,
    Hiccears,
    Hitomi,
    Imgur,
    Inkbunny,
    Itaku,
    Lofter,
    Mastodon,
    Nhentai,
    Paheal,
    Pillowfort,
    Pixiv,
    Poipiku,
    Rule34,
    Tiktok,
    Tumblr,
    Twitter,
    YGallery,
    YTCommunity,
]
